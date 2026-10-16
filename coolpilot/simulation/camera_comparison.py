"""Three-view, PTS-paced development replay; remote review is advisory only."""
import base64
import math
import os
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from time import perf_counter, process_time
from types import SimpleNamespace

import cv2
import numpy as np

from ..runtime import environment
from .camera_benchmark import ReviewBudget, replay
from .camera_effects import END, KINDS, START, effect, fields, strength
from ..models import CameraConfiguration, CameraThresholds, ReplayScenario

# COOLPILOT_DATA relocates the recordings (serverless hosts only write to /tmp); unset keeps the repo-relative path.
_DATA = Path(os.environ["COOLPILOT_DATA"]) if "COOLPILOT_DATA" in os.environ else Path(__file__).resolve().parents[2] / "data"
VIDEO_ROOT = _DATA / "oxford_robotcar" / "videos"
CAMERAS = {
    "left": {"label": "Left", "file": "stereo_left.mp4"},
    "centre": {"label": "Centre", "file": "stereo_centre.mp4"},
    "right": {"label": "Right", "file": "stereo_right.mp4"},
}
STREAM_FAULTS = (*KINDS[1:], "interruption", "jitter", "decode_failure", "timestamp_fault",
                 "processing_delay", "resolution")


def fault_schedule(faults: dict[str, str], duration: float, seed: int) -> dict[str, list[dict]]:
    """One seeded fault per non-reference source, with clean lead-in and recovery."""
    if duration <= 4:
        raise ValueError("Fault replay requires more than four seconds of source video.")
    rng = random.Random(seed)
    shuffled = list(STREAM_FAULTS)
    rng.shuffle(shuffled)
    schedule = {}
    for camera in CAMERAS:
        kinds = [] if faults[camera] == "reference" else [
            shuffled.pop() if faults[camera] == "random" else faults[camera]]
        events = []
        for kind in kinds:
            length = min(rng.uniform(2, 3), (duration - 4) / 2)
            start = rng.uniform(2, duration - 2 - length)
            event = {"kind": kind, "start_s": round(start, 3),
                     "end_s": round(start + length, 3)}
            if kind == "jitter":
                event["max_delay_ms"] = 250
            elif kind == "processing_delay":
                event["delay_ms"] = 700
            elif kind == "resolution":
                event["analysis_width_multiplier"] = 2
            events.append(event)
        schedule[camera] = events
    return schedule


def video_path(camera: str) -> Path:
    if camera not in CAMERAS:
        raise ValueError("Unknown camera view.")
    path = VIDEO_ROOT / CAMERAS[camera]["file"]
    if not path.is_file():
        raise FileNotFoundError("Oxford stereo preview is not available.")
    return path


def _source(camera: str, cancel: Event) -> dict:
    """Read container metadata only; validate decoded PTS as each frame arrives."""
    if cancel.is_set():
        raise ValueError("Replay cancelled.")
    path = video_path(camera)
    stat = path.stat()
    capture = cv2.VideoCapture(str(path))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not capture.isOpened() or not math.isfinite(fps) or fps <= 0 or not 0 < count <= 10000:
            raise ValueError("Stereo preview has invalid timing metadata.")
        duration = count / fps
        if not 0 < width <= 4096 or not 0 < height <= 2160 or duration > 60:
            raise ValueError("Stereo preview exceeds replay limits.")
        return {"camera": camera, "label": CAMERAS[camera]["label"], "width": width, "height": height,
                "frames": count, "source_fps": fps, "source_seconds": duration,
                "replay_seconds": duration + 1 / fps,
                "file_bytes": stat.st_size, "file_mtime_ns": stat.st_mtime_ns,
                "identity": "Allowlisted local path and size/mtime only; no full-file hash or predecode."}
    finally:
        capture.release()


def compare(faults: dict[str, str], config: CameraConfiguration, review_limit: int,
            timeout_s: float, emit, cancel: Event, seed: int) -> dict:
    sources = {camera: _source(camera, cancel) for camera in CAMERAS}
    schedule = fault_schedule(faults, min(s["source_seconds"] for s in sources.values()), seed)
    thresholds = CameraThresholds()
    settings = SimpleNamespace(thresholds=thresholds, allow_image_requests=config.mode != "local", api_timeout_s=timeout_s)
    facts = environment()
    metadata = {"type": "ready", "sources": list(sources.values()), "environment": facts,
                "configuration": config.model_dump(), "thresholds": thresholds.model_dump(),
                "faults": faults, "seed": seed, "schedule": schedule, "schedule_version": 2,
                "review_limit_per_camera": review_limit, "api_timeout_s": timeout_s}
    emit(metadata)
    masks = {camera: fields(s["height"], s["width"])
             if any(e["kind"] in ("glare", "obstruction") for e in schedule[camera]) else {}
             for camera, s in sources.items()}
    epoch = []
    barrier = Barrier(len(CAMERAS), action=lambda: epoch.append(perf_counter()))

    def run(camera):
        frozen, previous, frozen_event, last_frame, preview = None, None, None, None, None
        edit_ms = []
        events = schedule[camera]

        def transform(frame, pts):
            nonlocal frozen, previous, frozen_event
            active = next((e for e in events if e["start_s"] <= pts < e["end_s"]), None)
            kind = active["kind"] if active else "reference"
            started = perf_counter()
            if kind == "freeze" and frozen_event != active["start_s"]:
                frozen = previous if previous is not None else frame
                frozen_event = active["start_s"]
            previous = frame
            seconds = START + (pts - active["start_s"]) / (active["end_s"] - active["start_s"]) * (END - START) if active else 0
            edited = effect(frame, kind, seconds, frozen, masks[camera]) if kind in KINDS else frame
            edit_ms.append((perf_counter() - started) * 1000)
            return edited

        def observe(snapshot, frame):
            nonlocal last_frame, preview
            evidence = snapshot["evidence"]
            if frame is not None and evidence["frame"] != last_frame:
                height, width = frame.shape[:2]
                thumbnail = cv2.resize(frame, (320, round(height * 320 / width)), interpolation=cv2.INTER_AREA)
                ok, encoded = cv2.imencode(".jpg", thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise ValueError("Could not encode analyzed-frame preview.")
                preview = "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")
                last_frame = evidence["frame"]
            pts = evidence.get("pts_s")
            active = next((e for e in events if pts is not None and e["start_s"] <= pts < e["end_s"]), None)
            current = next((e["kind"] for e in events if e["start_s"] <= snapshot["time_s"] < e["end_s"]), "reference")
            kind = active["kind"] if active else "reference"
            seconds = START + (pts - active["start_s"]) / (active["end_s"] - active["start_s"]) * (END - START) if active else 0
            emit({"type": "frame", "camera": camera, **snapshot, "image": preview,
                  "injection": {"kind": kind, "current": current,
                                "strength": strength(kind, seconds) if kind in KINDS else 1},
                  "injection_p95_ms": float(np.percentile(edit_ms, 95)) if edit_ms else None})

        barrier.wait(timeout=10)
        try:
            trace = replay(str(video_path(camera)), None, sources[camera]["replay_seconds"],
                           ReplayScenario(clip=camera), config, settings, ReviewBudget(review_limit),
                           clock=epoch[0], transform=transform, observe=observe, cancel=cancel,
                           expected_frames=sources[camera]["frames"], fault_events=events,
                           seed=seed + list(CAMERAS).index(camera))
            stat = video_path(camera).stat()
            if (stat.st_size, stat.st_mtime_ns) != (sources[camera]["file_bytes"], sources[camera]["file_mtime_ns"]):
                raise ValueError("Source file changed during replay; evidence is invalid.")
            return {**sources[camera], "fault": faults[camera], "trace": trace,
                    "injection_p95_ms": float(np.percentile(edit_ms, 95)) if edit_ms else 0}
        except (ValueError, cv2.error) as error:
            emit({"type": "camera_error", "camera": camera, "error": str(error)})
            return {**sources[camera], "fault": faults[camera], "error": str(error), "status": "unavailable"}

    previous_threads, previous_opencl = cv2.getNumThreads(), cv2.ocl.useOpenCL()
    cv2.setNumThreads(config.threads)
    cv2.ocl.setUseOpenCL(False)
    start, cpu = perf_counter(), process_time()
    try:
        with ThreadPoolExecutor(max_workers=len(CAMERAS)) as pool:
            profiles = list(pool.map(run, CAMERAS))
        wall_s, cpu_s = perf_counter() - start, process_time() - cpu
    finally:
        cv2.setNumThreads(previous_threads)
        cv2.ocl.setUseOpenCL(previous_opencl)
    return {**metadata, "type": "complete", "cancelled": cancel.is_set(), "profiles": profiles,
            "measurement": {"concurrent_streams": len(CAMERAS), "wall_seconds": wall_s, "cpu_seconds": cpu_s,
                            "clock": "Shared monotonic epoch, incremental recorded PTS (not sensor time). Timelines validated per stream, not prevalidated stereo synchronization. CPU/wall include edits, previews and API cleanup; worker latency includes explicitly injected waits, compute_ms excludes them. Resolution events double analyzer width, not source resolution. Paced fps is coverage, not capacity."},
            "cool": {"available": facts["distribution"] == "COOL",
                     "detail": "Runtime identity is recorded; no acceleration or safety claim. COOL comparison requires matched runs on the licensed target."}}
