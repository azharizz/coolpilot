"""Real-time, bounded local replay. Run in the existing isolated experiment process."""
import argparse
import json
import math
import random
import resource
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import perf_counter, process_time

import cv2
import numpy as np

from ..runtime import environment
from ..camera_dataset import checked, public
from ..camera_health import Monitor, analyze, assess_health, score
from ..decisions import current_review, review
from ..models import CameraConfiguration, ReplayScenario, RunRequest


class ReviewBudget:
    def __init__(self, maximum):
        self.remaining = maximum
        self.lock = Lock()

    def take(self):
        with self.lock:
            if not self.remaining:
                return False
            self.remaining -= 1
            return True


def replay(video: str, timestamps: list[int] | None, duration: float, scenario: ReplayScenario,
           config: CameraConfiguration, settings, budget: ReviewBudget, *, clock: float | None = None,
           transform=None, observe=None, cancel: Event | None = None,
           expected_frames: int | None = None, fault_events: list[dict] | None = None, seed: int = 0) -> dict:
    """No labels, filenames-as-prompts, or injection recipes enter the analyzer/reviewer."""
    frames = Queue(maxsize=config.queue_size)
    stop = Event()
    lock = Lock()
    incremental = timestamps is None
    expected = expected_frames if incremental else len(timestamps)
    if expected is None or not 0 < expected <= 10000:
        raise ValueError("Replay needs a bounded source frame count.")
    source_timestamps = [] if incremental else timestamps
    events = fault_events or []
    random_delay = random.Random(seed)
    injected, rejected = [], []
    interrupted = 0 if incremental else sum(
        any(i.start_s <= timestamp / 1e6 < i.end_s for i in scenario.interruptions)
        for timestamp in timestamps)
    delivery = {"last": None, "count": 0, "dropped": 0, "done": False, "error": None, "max_lateness_s": 0.0}
    clock = perf_counter() if clock is None else clock

    def produce():
        nonlocal interrupted
        capture = cv2.VideoCapture(video)
        try:
            if not capture.isOpened() or not (0 < capture.get(cv2.CAP_PROP_FRAME_WIDTH) <= 4096 and 0 < capture.get(cv2.CAP_PROP_FRAME_HEIGHT) <= 2160):
                raise ValueError("Video cannot be decoded within dimension limits.")
            previous_pts = -1.0
            for index in range(expected):
                if stop.is_set() or (cancel is not None and cancel.is_set()):
                    break
                decode_started = perf_counter()
                ok, frame = capture.read()
                decode_ms = (perf_counter() - decode_started) * 1000
                if not ok:
                    raise ValueError("Video ended before its declared frame count.")
                pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if not math.isfinite(pts) or pts <= previous_pts or pts < 0 or pts >= duration or (index == 0 and pts != 0):
                    raise ValueError("Decoded source has invalid presentation timestamps.")
                previous_pts = pts
                if incremental:
                    source_timestamps.append(round(pts * 1e6))
                elif abs(pts - timestamps[index] / 1e6) > 0.002:
                    raise ValueError("Decoded PTS does not match the locked manifest.")
                arrival = pts if incremental else timestamps[index] / 1e6
                # Decode only the next frame; never preload pixels or scan the full source.
                if stop.wait(max(0, clock + arrival - perf_counter())):
                    break
                active = next((e for e in events if e["start_s"] <= arrival < e["end_s"]), None)
                kind = active["kind"] if active else None
                if active:
                    injected.append({"frame": index, "pts_s": arrival, "kind": kind})
                if kind == "interruption" or any(i.start_s <= arrival < i.end_s for i in scenario.interruptions):
                    if incremental or kind == "interruption":
                        interrupted += 1
                    continue
                # Mock faults are injected at the input boundary, not hidden inside analysis.
                if kind == "decode_failure":
                    frame = None
                received_pts = -1.0 if kind == "timestamp_fault" else arrival
                if frame is None or received_pts < 0:
                    rejected.append({"frame": index, "pts_s": arrival,
                                     "reason": "decode_failure" if frame is None else "timestamp_fault"})
                    continue
                if kind == "jitter":
                    delay = random_delay.uniform(0, active["max_delay_ms"]) / 1000
                    injected[-1]["delay_ms"] = delay * 1000
                    if stop.wait(delay):
                        break
                if transform is not None:
                    frame = transform(frame, arrival)
                now = perf_counter() - clock
                with lock:
                    delivery["last"] = now
                    delivery["count"] += 1
                    delivery["max_lateness_s"] = max(delivery["max_lateness_s"], now - arrival)
                item = (index, arrival, now, frame, decode_ms)
                try:
                    frames.put_nowait(item)
                except Full:
                    try:
                        frames.get_nowait()
                        with lock:
                            delivery["dropped"] += 1
                    except Empty:
                        pass
                    frames.put_nowait(item)
            if not stop.is_set() and capture.read()[0]:
                raise ValueError("Video contains frames absent from its timestamp manifest.")
        except Exception as error:
            with lock:
                delivery["error"] = f"Replay decoding failed ({type(error).__name__}): {error}"
        finally:
            capture.release()
            with lock:
                delivery["done"] = True

    producer = Thread(target=produce, daemon=True)
    producer.start()
    visual_monitor, delivery_monitor = Monitor(settings.thresholds), Monitor(settings.thresholds)
    local, unknown_intervals = set(), []
    evidence, observations, transitions, reviews = {}, [], [], []
    analysis_future = review_future = None
    frame_context = review_context = None
    review_frame = None
    next_review = 0.0
    last_result = None
    skipped, processed, max_queue, max_age, unknown_time = 0, 0, 0, 0.0, 0.0
    latency, decode_age, review_required = [], [], 0
    backlog_intervals, backlog_started = [], None
    previous_tick, previous_state, previous_unknown = 0.0, None, True
    display_frame = None
    next_update = 0.0

    def work(frame, source_time):
        started = perf_counter()
        interval = scenario.processing_delay_interval
        delay_ms = scenario.processing_delay_ms if interval and interval.start_s <= source_time < interval.end_s else 0
        active = next((e for e in events if e["start_s"] <= source_time < e["end_s"]), None)
        if active and active["kind"] == "processing_delay":
            delay_ms = active["delay_ms"]
        if delay_ms:
            stop.wait(delay_ms / 1000)
        analysis_started = perf_counter()
        width = config.width * 2 if active and active["kind"] == "resolution" else config.width
        result = analyze(frame, width)
        analysis_seconds = perf_counter() - analysis_started
        return result, perf_counter() - started, analysis_seconds, delay_ms, width

    try:
        with ThreadPoolExecutor(max_workers=1) as analysis_pool, ThreadPoolExecutor(max_workers=1) as review_pool:
            while True:
                now = perf_counter() - clock
                if now >= duration or (cancel is not None and cancel.is_set()):
                    break
                with lock:
                    transport = dict(delivery)
                if transport["error"]:
                    raise ValueError(transport["error"])
                fresh_observation = False
                if analysis_future and analysis_future.done():
                    result, elapsed, analysis_seconds, delay_ms, analysis_width = analysis_future.result()
                    index, scheduled, arrival, frame, decode_ms = frame_context
                    display_frame = frame
                    lateness = max(0.0, arrival - scheduled)
                    age = max(0.0, now - scheduled)
                    fresh_observation = age < min(settings.thresholds.feed_timeout_s, settings.thresholds.backlog_s)
                    regions = result["regions"]
                    if fresh_observation:
                        local, regions = visual_monitor.appearance(result, scheduled)
                    last_result = scheduled
                    review_frame = frame if fresh_observation else None
                    max_age = max(max_age, age)
                    latency.append(elapsed * 1000)
                    decode_age.append(decode_ms)
                    processed += 1
                    evidence = {"frame": index, "pts_s": scheduled, "analysis_s": now,
                                "arrival_age_s": max(0.0, now - arrival), "source_age_s": age,
                                "delivery_lateness_s": lateness, "regions": regions,
                                "black_fraction": result["black_fraction"],
                                "analysis_ms": elapsed * 1000, "decode_ms": decode_ms,
                                "compute_ms": analysis_seconds * 1000, "injected_delay_ms": delay_ms,
                                "analysis_width": analysis_width,
                                "local_conditions": sorted(local), "fresh": fresh_observation}
                    observations.append(evidence)
                    analysis_future = None
                    frame_context = None
                if review_future and review_future.done():
                    result = review_future.result()
                    reviews.append({**review_context, **result, "received_s": now})
                    if result["status"] != "ok" or now - review_context["requested_s"] > settings.api_timeout_s:
                        reviews[-1]["status"] = "unavailable"
                        reviews[-1].pop("probabilities", None)
                    reviews[-1]["valid_on_arrival"] = current_review(
                        reviews[-1], now,
                        min(settings.thresholds.feed_timeout_s, settings.thresholds.backlog_s),
                    )["status"] == "ok"
                    review_future = None
                if analysis_future is None:
                    try:
                        item = frames.get_nowait()
                        if item[0] % config.sample_every:
                            skipped += 1
                        else:
                            frame_context = item
                            analysis_future = analysis_pool.submit(work, item[3], item[1])
                    except Empty:
                        pass
                max_queue = max(max_queue, frames.qsize())
                last = transport["last"]
                unavailable = (now - last if last is not None else now) >= settings.thresholds.feed_timeout_s
                outstanding_age = now - frame_context[1] if frame_context else 0
                with frames.mutex:
                    if frames.queue:
                        outstanding_age = max(outstanding_age, now - frames.queue[0][1])
                max_age = max(max_age, outstanding_age)
                evidence_age = now - last_result if last_result is not None else None
                if evidence_age is not None:
                    max_age = max(max_age, evidence_age)
                stale = evidence_age is None or evidence_age >= min(settings.thresholds.feed_timeout_s, settings.thresholds.backlog_s)
                unknown = unavailable or stale
                if settings.allow_image_requests and config.mode != "local":
                    while now >= next_review:
                        due = next_review
                        next_review += config.review_interval_s
                        if config.mode == "hybrid" and (unknown or not local):
                            continue
                        review_required += 1
                        context = {"due_s": due, "frame": evidence.get("frame"),
                                   "pts_s": evidence.get("pts_s"), "attempted": False}
                        if review_future is not None:
                            reviews.append({**context, "status": "busy"})
                        elif unknown or review_frame is None:
                            reviews.append({**context, "status": "no_evidence"})
                        elif not budget.take():
                            reviews.append({**context, "status": "budget_exhausted"})
                        else:
                            review_context = {**context, "attempted": True, "requested_s": now}
                            review_future = review_pool.submit(review, review_frame, settings.api_timeout_s)
                if previous_unknown:
                    unknown_time += now - previous_tick
                if unknown and (not previous_unknown or previous_state is None):
                    unknown_intervals.append({"start_s": previous_tick if previous_state is None else now,
                                              "end_s": None, "reason": "insufficient_or_stale_evidence"})
                elif not unknown and previous_unknown and unknown_intervals:
                    unknown_intervals[-1]["end_s"] = now
                previous_unknown = unknown
                if unknown:
                    # Missing evidence cannot establish persistence, recovery, or frozen content.
                    visual_monitor.pending.clear()
                    visual_monitor.clearing.clear()
                    visual_monitor.previous = None
                    visual_monitor.unchanged_since = None
                conditions = set()
                if unavailable:
                    conditions.add("interruption")
                if outstanding_age >= settings.thresholds.backlog_s:
                    conditions.add("backlog")
                    if backlog_started is None:
                        backlog_started = now
                elif backlog_started is not None:
                    backlog_intervals.append({"type": "backlog", "start_s": backlog_started, "end_s": now,
                                              "provenance": "measured_queue_age", "severity": "configured backlog threshold"})
                    backlog_started = None
                # Visual persistence advances only when a new analyzed frame arrives.
                if fresh_observation:
                    visual_monitor.update(local, now, evidence)
                delivery_monitor.update(conditions & {"interruption", "backlog"}, now, evidence)
                health = assess_health(unavailable=unavailable, stale=stale,
                                       delivery_conditions=set(delivery_monitor.active),
                                       visual_conditions=set(visual_monitor.active))
                state = (tuple(health["delivery_conditions"]), tuple(health["visual_conditions"]),
                         health["pipeline_status"], health["quality_status"])
                if state != previous_state:
                    transitions.append({"time_s": now, **health, "unknown": unknown,
                                        "evidence_age_s": evidence_age,
                                        "delivery": "unavailable" if unavailable else "arriving",
                                        "queue_age_s": outstanding_age, "frame": evidence.get("frame")})
                    previous_state = state
                if observe is not None and now >= next_update:
                    next_update = now + 0.1
                    attempted = [r for r in reviews if r.get("attempted")]
                    costs = [r.get("cost") for r in attempted]
                    observe({
                        "time_s": now, **health,
                        "evidence": evidence, "evidence_age_s": evidence_age,
                        "processed": processed, "delivered": transport["count"], "dropped": transport["dropped"],
                        "interrupted": interrupted, "rejected": len(rejected),
                        "queue_depth": frames.qsize(), "processed_fps": processed / now if now else 0,
                        "analysis_p95_ms": float(np.percentile(latency, 95)) if latency else None,
                        "review_pending": review_context if review_future is not None else None,
                        "review_slot": reviews[-1] if reviews else None,
                        "review_result": attempted[-1] if attempted else None,
                        "review_current": current_review(
                            attempted[-1] if attempted else None, now,
                            min(settings.thresholds.feed_timeout_s, settings.thresholds.backlog_s)),
                        "review_attempts": len(attempted) + int(review_future is not None),
                        "review_cost": sum(c for c in costs if c is not None),
                        "review_cost_complete": all(c is not None for c in costs) and review_future is None,
                        "episodes": [{"type": e["type"], "observation": e["observation"],
                                      "start_s": e["start_s"], "end_s": e["end_s"]}
                                     for e in visual_monitor.episodes + delivery_monitor.episodes],
                    }, display_frame)
                previous_tick = now
                stop.wait(min(0.02, max(0, duration - now)))
            end_time = min(duration, perf_counter() - clock)
            stop.set()
            if review_future:
                result = review_future.result()
                reviews.append({**review_context, **result, "status": "unavailable",
                                "received_s": perf_counter() - clock, "late": True,
                                "valid_on_arrival": False})
                reviews[-1].pop("probabilities", None)
            producer.join()
    finally:
        stop.set()
        producer.join()
    if delivery["error"]:
        raise ValueError(delivery["error"])
    if settings.allow_image_requests and config.mode == "scheduled":
        while next_review < end_time:
            reviews.append({"due_s": next_review, "attempted": False, "status": "replay_ended"})
            review_required += 1
            next_review += config.review_interval_s
    # Include source frames never delivered or still decoding at the cutoff.
    unfinished = expected - interrupted - len(rejected) - processed - skipped - delivery["dropped"]
    if previous_unknown:
        unknown_time += max(0.0, end_time - previous_tick)
    if unknown_intervals and unknown_intervals[-1]["end_s"] is None:
        unknown_intervals[-1]["end_s"] = end_time
    if backlog_started is not None:
        backlog_intervals.append({"type": "backlog", "start_s": backlog_started, "end_s": end_time,
                                  "provenance": "measured_queue_age", "severity": "configured backlog threshold"})
    episodes = sorted(visual_monitor.episodes + delivery_monitor.episodes, key=lambda e: e["start_s"])
    return {"episodes": episodes, "unknown_intervals": unknown_intervals, "backlog_intervals": backlog_intervals,
            "transitions": transitions, "observations": observations, "reviews": reviews,
            "duration_s": end_time, "cancelled": cancel is not None and cancel.is_set(),
            "expected_frames": expected, "decoded_frames": len(source_timestamps) if incremental else None,
            "timestamps_us": source_timestamps if incremental else None,
            "injections": injected, "rejected_frames": len(rejected), "rejections": rejected,
            "interrupted_frames": interrupted,
            "processed": processed, "skipped": skipped,
            "dropped": delivery["dropped"], "delivered": delivery["count"], "max_queue": max_queue,
            "max_age_s": max_age, "unknown_fraction": min(1, unknown_time / end_time) if end_time else 1,
            "unfinished_frames": unfinished, "analysis_ms": latency,
            "max_delivery_lateness_s": delivery["max_lateness_s"], "decode_ms": decode_age,
            "review_required": review_required}


def cost_per_camera_hour(elapsed_s: float, camera_s: float, host_rate: float,
                         cool_rate: float, image_cost: float) -> float:
    return ((host_rate + cool_rate) * elapsed_s / 3600 + image_cost) * 3600 / camera_s


def benchmark(request: RunRequest, config: CameraConfiguration, split: str) -> dict:
    settings = request.camera
    dataset = checked(settings)
    if config.mode != "local" and not (settings.allow_image_requests and settings.max_image_requests):
        raise ValueError("Remote configuration requires explicit permission and budget.")
    selected_split = "development_only" if dataset["development_only"] else split
    clips = [c for c in dataset["clips"] if c["split"] == selected_split]
    if not clips or (split == "validation" and dataset["development_only"]):
        raise ValueError("No independent validation recordings are registered.")
    cv2.setNumThreads(config.threads)
    cv2.ocl.setUseOpenCL(False)
    start, cpu = perf_counter(), process_time()
    budget = ReviewBudget(settings.max_image_requests)
    traces, evaluations, repetitions = [], [], []
    scenarios = {s.clip: s for s in settings.scenarios}
    for repetition in range(request.repetitions):
        counted, normal, false_alarms = {}, 0.0, 0
        for clip in clips:
            scenario = scenarios.get(clip["id"], ReplayScenario(clip=clip["id"]))
            with ThreadPoolExecutor(max_workers=settings.concurrent_streams) as pool:
                futures = [pool.submit(replay, clip["file"], clip["timestamps_us"], clip["duration_s"], scenario,
                                       config, settings, budget) for _ in range(settings.concurrent_streams)]
                results = [future.result() for future in futures]
            for stream, result in enumerate(results):
                truth = list(clip["events"]) + [{"type": "interruption", "start_s": i.start_s, "end_s": i.end_s,
                                                "provenance": "synthetic_delivery", "severity": "complete delivery pause"}
                                               for i in scenario.interruptions] + result["backlog_intervals"]
                scored = score(truth, result["episodes"], clip["duration_s"], result["unknown_intervals"])
                by_fault = {}
                for kind in {e["type"] for e in truth}:
                    rows = [m for m in scored["matches"] if m["type"] == kind]
                    severity = {}
                    for item in rows:
                        key = f"{item.get('severity', 'unspecified')} / {item.get('provenance', 'unspecified')}"
                        grouped = severity.setdefault(key, {"events": 0, "missed": 0})
                        grouped["events"] += 1
                        grouped["missed"] += not item["detected"]
                    by_fault[kind] = {"events": len(rows), "missed": sum(not m["detected"] for m in rows),
                                      "recall": sum(m["detected"] for m in rows) / len(rows),
                                      "detection_s": max((m["detection_s"] for m in rows if m["detection_s"] is not None), default=None),
                                      "recovery_s": max((m["recovery_s"] for m in rows if m["recovery_s"] is not None), default=None),
                                      "bad_recovery": sum(m["premature_clear"] or m["failed_clear"] for m in rows),
                                      "by_severity_provenance": severity}
                    # Replicas measure load, not independent event evidence.
                    if stream == 0:
                        counted[kind] = counted.get(kind, 0) + len(rows)
                reviews = [r for r in result["reviews"] if r["attempted"]]
                api_failures = sum(not r["valid_on_arrival"] for r in reviews)
                attempts = len(reviews)
                successes = attempts - api_failures
                row = {"clip": clip["id"], "repetition": repetition, "stream": stream, "by_fault": by_fault,
                       **{k: result[k] for k in ("max_age_s", "unknown_fraction", "unfinished_frames", "dropped", "skipped", "processed", "max_queue", "max_delivery_lateness_s", "review_required")},
                       "api_failure_fraction": api_failures / attempts if attempts else 0.0,
                       "review_coverage": successes / result["review_required"] if result["review_required"] else None}
                evaluations.append(row)
                traces.append({**row, **result, "scoring": scored, "truth": truth, "session": clip["session"],
                               "camera": clip["camera"], "sha256": clip["sha256"]})
                if stream == 0:
                    normal += scored["normal_seconds"]
                false_alarms += len(scored["false_alarms"])
        repetitions.append({"repetition": repetition, "event_counts": counted, "normal_seconds": normal,
                            "false_alarms_per_hour": false_alarms * 3600 / (normal * settings.concurrent_streams) if normal else None})
    elapsed, cpu_seconds = perf_counter() - start, process_time() - cpu
    camera_seconds = sum(t["duration_s"] for t in traces)
    reviews = [r for t in traces for r in t["reviews"] if r["attempted"]]
    model_cost = sum(r["cost"] for r in reviews) if all(r.get("cost") is not None for r in reviews) else None
    cost = None
    if request.hourly_price is not None and settings.cool_hourly_price is not None and model_cost is not None:
        cost = cost_per_camera_hour(elapsed, camera_seconds, request.hourly_price,
                                    settings.cool_hourly_price, model_cost)
    durations = [ms for t in traces for ms in t["analysis_ms"]]
    decode = [ms for t in traces for ms in t["decode_ms"]]
    metrics = {"evaluations": evaluations, "repetition_evidence": repetitions,
               "cpu_seconds_per_camera_second": cpu_seconds / camera_seconds, "cpu_seconds": cpu_seconds,
               "wall_seconds": elapsed, "camera_seconds": camera_seconds,
               "p95_ms": float(np.percentile(durations, 95)) if durations else None,
               "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 2 if sys.platform == "darwin" else 1024),
               "max_age_s": max(e["max_age_s"] for e in evaluations),
               "cost_per_camera_hour": cost, "image_requests": len(reviews), "image_cost": model_cost,
               "streams_tested": settings.concurrent_streams,
               "capacity_note": "Fixed-count replicas, not a maximum or heterogeneous fleet capacity measurement.",
               "freshness_basis": "Maximum age from scheduled source-frame time to completed local analysis; upstream capture/network age is unavailable.",
               "cost_exclusions": "Storage, network, optimizer tokens and operator time; unknown prices are never zero-filled."}
    return {"workload": "camera_health", "schema_version": 1, "config": config.model_dump(), "split": selected_split,
            "repetitions": request.repetitions, "dataset_sha256": dataset["sha256"], "dataset": public(dataset),
            "metrics": metrics, "environment": environment(), "trace": {"streams": traces}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", choices=("tuning", "validation"), required=True)
    args = parser.parse_args()
    print(json.dumps(benchmark(RunRequest.model_validate_json(args.request.read_text()),
                               CameraConfiguration.model_validate_json(args.config.read_text()), args.split), allow_nan=False))
