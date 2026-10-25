"""Camera-footage quality gate: screen one uploaded recording and report unhealthy segments.

Use case: before footage is labelled, used for training or reviewed after an incident, flag the
segments where the camera itself was the problem (black, frozen, blurred, dark, glare, suspected
obstruction). Unpaced: every frame is analysed once, as fast as the host allows. Obstruction
suspicions go through the rule verifier (coolpilot.verify) before they are reported.

Not a safety monitor. Calibrated on one Oxford drive and DRIVE-C dev scenes; rain and real lens dirt
are unvalidated, and footage dark from its first frame is treated as night (a camera dark from power-on
is not flagged). The caller deletes the file; nothing here stores it.
"""
import base64
import time
from collections import deque

import cv2

from . import verify
from .camera_health import Monitor, analyze
from .models import CameraThresholds

MAX_SECONDS = 60
MAX_BYTES = 50 * 1024 * 1024


def thumbnail(frame) -> str:
    h, w = frame.shape[:2]
    ok, data = cv2.imencode(".jpg", cv2.resize(frame, (240, round(h * 240 / w)), interpolation=cv2.INTER_AREA),
                            [cv2.IMWRITE_JPEG_QUALITY, 70])
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii") if ok else ""


def frames_of(capture):
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                return
            yield frame
    finally:
        capture.release()


def screen(path: str, emit=None, width: int = 640, thresholds: CameraThresholds | None = None) -> dict:
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise ValueError("The file could not be opened as a video.")
    fps = capture.get(cv2.CAP_PROP_FPS) or 0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0 or total <= 0:
        capture.release()
        raise ValueError("The video has no usable frame rate or frame count.")
    if total / fps > MAX_SECONDS + 0.5:
        capture.release()
        raise ValueError(f"The video is {total / fps:.0f} s long; the limit is {MAX_SECONDS} s.")
    return screen_frames(frames_of(capture), fps, total, emit, width, thresholds)


def screen_frames(frames, fps: float, total: int, emit=None, width: int = 640, thresholds: CameraThresholds | None = None) -> dict:
    """Screen any frame sequence at a fixed rate (an uploaded file, or clips joined for evaluation)."""
    monitor, recent, decisions, thumbs = Monitor(thresholds or CameraThresholds()), deque(), [], {}
    started, cpu = time.perf_counter(), time.process_time()
    index, last_emit, frame_shape, suppress = 0, 0.0, None, False
    try:
        for frame in frames:
            t = index / fps   # container timing; recordings with variable timing are approximated
            frame_shape = frame.shape[:2]
            conditions, regions = monitor.appearance(analyze(frame, width), t)
            # One verdict per continuous suspicion: after a dismissal, ignore it until the condition clears.
            if suppress:
                if "obstruction" in conditions:
                    conditions = conditions - {"obstruction"}
                else:
                    suppress = False
            h, w = frame.shape[:2]
            recent.append((t, cv2.resize(frame, (640, round(h * 640 / w)), interpolation=cv2.INTER_AREA)))
            while t - recent[0][0] > 1.0:
                recent.popleft()
            before = len(monitor.episodes)
            monitor.update(conditions, t, {})
            for episode in monitor.episodes[before:]:
                thumbs[id(episode)] = thumbnail(frame)
                if episode["type"] == "obstruction":
                    tiles = [i for i, r in enumerate(regions) if r["suspected_obstruction"]]
                    evidence = verify.gather([f for _, f in recent], [r["box"] for r in regions], tiles, monitor.recent_detail.tolist())
                    verdict = verify.rule_verdict(evidence, tiles)
                    episode["verification"] = {"verdict": verdict["verdict"], "reason": verdict["reason"], "tiles": tiles,
                                               "engine": evidence["objects"].get("engine")}
                    decisions.append({"time_s": round(t, 2), **episode["verification"]})
                    if verdict["verdict"] == "dismiss":
                        episode["dismissed"] = True
                        monitor.active.pop("obstruction", None)
                        monitor.pending.pop("obstruction", None)
                        suppress = True
            index += 1
            if emit and time.perf_counter() - last_emit > 0.5:
                last_emit = time.perf_counter()
                emit({"type": "progress", "frames": index, "total": total})
    finally:
        close = getattr(frames, "close", None)
        if close:
            close()
    duration = index / fps if fps else 0.0
    wall, cpu_s = time.perf_counter() - started, time.process_time() - cpu
    segments = []
    for e in monitor.episodes:
        if e.get("dismissed"):
            continue
        end = e["end_s"] if e["end_s"] is not None else duration
        segments.append({"type": e["type"], "observation": e["observation"], "start_s": round(e["start_s"], 2),
                         "end_s": round(end, 2), "open_at_end": e["end_s"] is None, "thumbnail": thumbs.get(id(e), ""),
                         "verification": e.get("verification")})
    flagged = sum(s["end_s"] - s["start_s"] for s in segments)
    return {"type": "report", "frames": index, "fps": round(fps, 2), "duration_s": round(duration, 2),
            "resolution": list(reversed(frame_shape)) if frame_shape else None,
            "segments": segments, "verifier_decisions": decisions,
            "flagged_seconds": round(min(flagged, duration), 2),
            # Dark from its first frame: night driving, or a camera dark since power-on. Not raised as a fault.
            "dark_since_start": monitor.dark_since_start and index > 0, "processing_s": round(wall, 2), "cpu_s": round(cpu_s, 2),
            "speed_x_realtime": round(duration / wall, 1) if wall else None,
            "opencv": cv2.__version__,
            "scope": "Screens for camera-side problems only. Calibrated on one Oxford drive and DRIVE-C dev scenes with synthetic faults. "
                     "Footage dark from its first frame is treated as night, not a fault. Not validated for rain or real lens dirt, "
                     "and never a safety judgement."}
