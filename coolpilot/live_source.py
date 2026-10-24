"""Monitor-only analysis of a live camera (device, RTSP/HTTP stream or file) with OpenCV VideoCapture.

Not tested against a real camera. There is no ground truth, so nothing is scored: the output is the
same health channels and suspicions as a replay, timed by wall-clock arrival. Sources are configured
by the operator only, never by the client:

    COOLPILOT_LIVE_SOURCES="dashcam=rtsp://192.168.1.20/stream,usb=0"
"""
import os
import time

import cv2

from .camera_health import Monitor, analyze, assess_health
from .models import CameraThresholds


def sources() -> dict[str, str]:
    entries = (item.split("=", 1) for item in os.environ.get("COOLPILOT_LIVE_SOURCES", "").split(",") if "=" in item)
    return {name.strip(): target.strip() for name, target in entries if name.strip() and target.strip()}


def open_capture(target: str):
    capture = cv2.VideoCapture(int(target) if target.isdigit() else target)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # prefer the newest frame over a backlog (ignored by some backends)
    return capture


def monitor(target: str, seconds: float, emit, cancel, *, width: int = 640, thresholds: CameraThresholds | None = None,
            max_reconnects: int = 5, emit_every_s: float = 0.5) -> dict:
    """Analyse frames until `seconds` pass, `cancel` is set or the source stays unavailable."""
    thresholds = thresholds or CameraThresholds()
    health = Monitor(thresholds)
    start = last_frame = last_emit = time.monotonic()
    capture, frames, reconnects, backoff, unavailable = open_capture(target), 0, 0, 0.5, False
    # A camera blocks on read() at its own rate; a file would be read as fast as possible, so pace it.
    period = 1 / capture.get(cv2.CAP_PROP_FPS) if os.path.isfile(target) and capture.get(cv2.CAP_PROP_FPS) > 0 else 0.0
    conditions: set[str] = set()
    try:
        while not cancel.is_set() and (now := time.monotonic()) - start < seconds:
            ok, frame = capture.read() if capture.isOpened() else (False, None)
            if not ok:
                # Feed timeout: report unavailable, then reconnect with exponential backoff.
                unavailable = now - last_frame >= thresholds.feed_timeout_s
                if reconnects >= max_reconnects:
                    break
                capture.release()
                time.sleep(min(backoff, max(0.0, seconds - (now - start))))
                backoff, reconnects = min(backoff * 2, 8.0), reconnects + 1
                capture = open_capture(target)
            else:
                if period:
                    time.sleep(max(0.0, last_frame + period - time.monotonic()))
                    now = time.monotonic()
                last_frame, backoff, unavailable = now, 0.5, False
                frames += 1
                conditions, _ = health.appearance(analyze(frame, width), now - start)
                health.update(conditions, now - start, {})
            if now - last_emit >= emit_every_s:
                last_emit = now
                emit({"type": "live", "elapsed_s": round(now - start, 2), "frames": frames, "reconnects": reconnects,
                      **assess_health(unavailable=unavailable, stale=False, delivery_conditions=set(),
                                      visual_conditions=set(health.active))})
    finally:
        capture.release()
    elapsed = time.monotonic() - start
    return {"type": "result", "frames": frames, "seconds": round(elapsed, 2), "fps": round(frames / elapsed, 2) if elapsed else 0,
            "reconnects": reconnects, "episodes": health.episodes, "scored": False,
            "note": "Monitor-only: a live source has no labels, so recall and false alarms are not measured."}
