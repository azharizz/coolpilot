"""Synchronized Oxford stereo preview and measured local OpenCV comparison."""
from pathlib import Path
from time import perf_counter, thread_time

import cv2
import numpy as np

from .camera_health import analyze
from .decisions import compare as compare_decisions

VIDEO_ROOT = Path(__file__).resolve().parent.parent / "data" / "oxford_robotcar" / "videos"
CAMERAS = {
    "left": {"label": "Left", "file": "stereo_left.mp4"},
    "centre": {"label": "Centre", "file": "stereo_centre.mp4"},
    "right": {"label": "Right", "file": "stereo_right.mp4"},
}
DISTRIBUTION = "COOL" if str(cv2.__file__).startswith("/opt/cool/") else "OpenCV"


def video_path(camera: str) -> Path:
    if camera not in CAMERAS:
        raise ValueError("Unknown camera view.")
    path = VIDEO_ROOT / CAMERAS[camera]["file"]
    if not path.is_file():
        raise FileNotFoundError("Oxford stereo preview is not available.")
    return path


def _profile(camera: str) -> dict:
    capture = cv2.VideoCapture(str(video_path(camera)))
    if not capture.isOpened():
        raise ValueError("Could not open stereo preview.")
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    frames_reported = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if source_fps <= 0 or frames_reported <= 0:
        capture.release()
        raise ValueError("Stereo preview has invalid timing metadata.")

    analysis_ms = []
    brightness = []
    detail = []
    black_fraction = []
    cpu_start = thread_time()
    total_start = perf_counter()
    read_s = 0.0
    frames = 0
    while True:
        start = perf_counter()
        ok, frame = capture.read()
        read_s += perf_counter() - start
        if not ok:
            break
        start = perf_counter()
        metrics = analyze(frame, 320)
        analysis_ms.append((perf_counter() - start) * 1000)
        brightness.append(float(np.mean([region["mean"] for region in metrics["regions"]])))
        detail.append(float(np.mean([region["detail"] for region in metrics["regions"]])))
        black_fraction.append(metrics["black_fraction"])
        frames += 1
    wall_s = perf_counter() - total_start
    cpu_s = thread_time() - cpu_start
    capture.release()
    if frames != frames_reported or not analysis_ms:
        raise ValueError("Stereo preview ended before its declared frame count.")

    source_s = frames / source_fps
    return {
        "camera": camera,
        "label": CAMERAS[camera]["label"],
        "width": width,
        "height": height,
        "frames": frames,
        "source_fps": source_fps,
        "source_seconds": source_s,
        "decode_ms_per_frame": read_s * 1000 / frames,
        "analysis_p95_ms": float(np.percentile(analysis_ms, 95)),
        "processing_fps": frames / wall_s if wall_s else None,
        "wall_seconds": wall_s,
        "cpu_seconds_per_source_second": cpu_s / source_s,
        "mean_brightness": float(np.mean(brightness)),
        "mean_detail": float(np.mean(detail)),
        "black_fraction": float(np.mean(black_fraction)),
        "runtime": DISTRIBUTION,
    }


def profile_all() -> list[dict]:
    return [_profile(camera) for camera in CAMERAS]


def _frame(camera: str, at_s: float):
    capture = cv2.VideoCapture(str(video_path(camera)))
    if not capture.isOpened():
        raise ValueError("Could not open stereo preview.")
    duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS)
    if at_s >= duration:
        capture.release()
        raise ValueError("Sample time is outside the source video.")
    capture.set(cv2.CAP_PROP_POS_MSEC, at_s * 1000)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise ValueError("Could not decode the selected camera frame.")
    return frame


def compare(sample_time_s: float, request_decision: bool) -> dict:
    profiles = profile_all()
    frames = {camera: _frame(camera, sample_time_s) for camera in CAMERAS}
    visual = compare_decisions(frames, timeout_s=20) if request_decision else {
        "status": "not_requested", "cost": None,
    }
    cool_available = DISTRIBUTION == "COOL"
    return {
        "sample_time_s": sample_time_s,
        "profiles": profiles,
        "decision": visual,
        "cool": {
            "available": cool_available,
            "detail": "Measured with the COOL-linked OpenCV build." if cool_available else "This host runs local OpenCV; a licensed compatible Graviton COOL runtime is required for COOL measurements.",
        },
    }
