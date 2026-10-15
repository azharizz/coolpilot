"""Real-time, bounded local replay. Run in the existing isolated experiment process."""
import argparse
import json
import resource
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import perf_counter, process_time

import cv2
import numpy as np

from .benchmark import environment
from .camera_dataset import checked, public
from .camera_health import Monitor, analyze, score
from .decisions import review
from .models import CameraConfiguration, ReplayScenario, RunRequest


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


def replay(video: str, timestamps: list[int], duration: float, scenario: ReplayScenario,
           config: CameraConfiguration, settings, budget: ReviewBudget) -> dict:
    """No labels, filenames-as-prompts, or injection recipes enter the analyzer/reviewer."""
    frames = Queue(maxsize=config.queue_size)
    stop = Event()
    lock = Lock()
    delivery = {"last": None, "count": 0, "dropped": 0, "done": False, "error": None, "max_lateness_s": 0.0}
    clock = perf_counter()

    def produce():
        capture = cv2.VideoCapture(video)
        try:
            if not capture.isOpened() or not (0 < capture.get(cv2.CAP_PROP_FRAME_WIDTH) <= 4096 and 0 < capture.get(cv2.CAP_PROP_FRAME_HEIGHT) <= 2160):
                raise ValueError("Video cannot be decoded within dimension limits.")
            for index, timestamp in enumerate(timestamps):
                if stop.is_set():
                    break
                decode_started = perf_counter()
                ok, frame = capture.read()
                decode_ms = (perf_counter() - decode_started) * 1000
                if not ok:
                    raise ValueError("Video ended before its timestamp manifest.")
                pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                if abs(pts - timestamp / 1e6) > 0.002:
                    raise ValueError("Decoded PTS does not match the locked manifest.")
                arrival = timestamp / 1e6
                if stop.wait(max(0, clock + arrival - perf_counter())):
                    break
                if any(i.start_s <= arrival < i.end_s for i in scenario.interruptions):
                    continue
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
                delivery["error"] = f"Replay decoding failed ({type(error).__name__})."
        finally:
            capture.release()
            with lock:
                delivery["done"] = True

    producer = Thread(target=produce, daemon=True)
    producer.start()
    visual_monitor, delivery_monitor = Monitor(settings.thresholds), Monitor(settings.thresholds)
    local, remote, unknown_intervals = set(), set(), []
    evidence, observations, transitions, reviews = {}, [], [], []
    analysis_future = review_future = None
    frame_context = review_context = None
    next_review, remote_until = 0.0, 0.0
    last_result = None
    skipped, processed, max_queue, max_age, unknown_time = 0, 0, 0, 0.0, 0.0
    latency, decode_age, review_required = [], [], 0
    backlog_intervals, backlog_started = [], None
    previous_tick, previous_state, previous_unknown = 0.0, None, False

    def work(frame, source_time):
        started = perf_counter()
        interval = scenario.processing_delay_interval
        if interval and interval.start_s <= source_time < interval.end_s:
            stop.wait(scenario.processing_delay_ms / 1000)
        result = analyze(frame, config.width)
        return result, perf_counter() - started

    try:
        with ThreadPoolExecutor(max_workers=1) as analysis_pool, ThreadPoolExecutor(max_workers=1) as review_pool:
            while True:
                now = perf_counter() - clock
                if now >= duration:
                    break
                with lock:
                    transport = dict(delivery)
                if transport["error"]:
                    raise ValueError(transport["error"])
                fresh_observation = False
                if analysis_future and analysis_future.done():
                    result, elapsed = analysis_future.result()
                    index, scheduled, arrival, frame, decode_ms = frame_context
                    lateness = max(0.0, arrival - scheduled)
                    local, regions = visual_monitor.appearance(result, now)
                    last_result = now
                    age = max(0.0, now - scheduled)
                    max_age = max(max_age, age)
                    latency.append(elapsed * 1000)
                    decode_age.append(decode_ms)
                    processed += 1
                    evidence = {"frame": index, "pts_s": scheduled, "analysis_s": now, "arrival_age_s": age,
                                "delivery_lateness_s": lateness, "regions": regions,
                                "local_conditions": sorted(local)}
                    observations.append(evidence)
                    fresh_observation = True
                    wants_review = config.mode == "scheduled" or (config.mode == "hybrid" and bool(local))
                    if settings.allow_image_requests and wants_review and review_future is None and now >= next_review:
                        review_required += 1
                        next_review = now + config.review_interval_s
                        if budget.take():
                            review_context = {"frame": index, "requested_s": now}
                            review_future = review_pool.submit(review, frame, settings.api_timeout_s)
                        else:
                            reviews.append({"frame": index, "requested_s": now, "status": "budget_exhausted"})
                    analysis_future = None
                    frame_context = None
                if review_future and review_future.done():
                    result = review_future.result()
                    reviews.append({**review_context, **result, "received_s": now})
                    if result["status"] == "ok" and now - review_context["requested_s"] <= settings.api_timeout_s:
                        remote = {k for k, p in result["probabilities"].items() if p >= settings.thresholds.decision_probability}
                        remote_until = now + config.review_interval_s
                    else:
                        remote = set()
                        reviews[-1]["status"] = "unavailable"
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
                stale = last_result is None or now - last_result > settings.thresholds.feed_timeout_s
                unknown = unavailable or stale
                if unknown and not previous_unknown:
                    unknown_intervals.append({"start_s": now, "end_s": None, "reason": "insufficient_or_stale_evidence"})
                elif not unknown and previous_unknown:
                    unknown_intervals[-1]["end_s"] = now
                previous_unknown = unknown
                if unknown:
                    unknown_time += now - previous_tick
                conditions = (local if config.mode != "scheduled" else local & {"freeze"}) | (remote if now < remote_until else set())
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
                    visual_monitor.update((local if config.mode != "scheduled" else local & {"freeze"}) |
                                          (remote if now < remote_until else set()), now, evidence)
                delivery_monitor.update(conditions & {"interruption", "backlog"}, now, evidence)
                active_conditions = set(visual_monitor.active) | set(delivery_monitor.active)
                state = (tuple(sorted(active_conditions)), unknown, unavailable)
                if state != previous_state:
                    transitions.append({"time_s": now, "conditions": list(state[0]), "unknown": unknown,
                                        "delivery": "unavailable" if unavailable else "arriving",
                                        "queue_age_s": outstanding_age, "frame": evidence.get("frame")})
                    previous_state = state
                previous_tick = now
                stop.wait(min(0.02, max(0, duration - now)))
            unfinished = frames.qsize() + int(analysis_future is not None)
            stop.set()
            if review_future:
                result = review_future.result()
                reviews.append({**review_context, **result, "received_s": perf_counter() - clock, "late": True})
            producer.join()
    finally:
        stop.set()
        producer.join()
    if delivery["error"]:
        raise ValueError(delivery["error"])
    if unknown_intervals and unknown_intervals[-1]["end_s"] is None:
        unknown_intervals[-1]["end_s"] = duration
    if backlog_started is not None:
        backlog_intervals.append({"type": "backlog", "start_s": backlog_started, "end_s": duration,
                                  "provenance": "measured_queue_age", "severity": "configured backlog threshold"})
    episodes = sorted(visual_monitor.episodes + delivery_monitor.episodes, key=lambda e: e["start_s"])
    return {"episodes": episodes, "unknown_intervals": unknown_intervals, "backlog_intervals": backlog_intervals,
            "transitions": transitions, "observations": observations, "reviews": reviews,
            "duration_s": duration, "processed": processed, "skipped": skipped,
            "dropped": delivery["dropped"], "delivered": delivery["count"], "max_queue": max_queue,
            "max_age_s": max_age, "unknown_fraction": min(1, unknown_time / duration),
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
                reviews = result["reviews"]
                api_failures = sum(r["status"] != "ok" or r.get("late", False) for r in reviews
                                   if r["status"] != "budget_exhausted")
                attempts = sum(r["status"] != "budget_exhausted" for r in reviews)
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
    reviews = [r for t in traces for r in t["reviews"] if r["status"] != "budget_exhausted"]
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
