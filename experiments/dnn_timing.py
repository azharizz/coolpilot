"""Time the verifier's road-user detector (NanoDet) on this interpreter's OpenCV build.

    python -m experiments.dnn_timing --out results/dnn-5x.json

OpenCV 5 loads it on the new graph engine; 4.x on the classic engine. Run both on the same host to compare.
"""
import argparse
import json
import platform
import statistics
from pathlib import Path

import cv2

from coolpilot import objects

CLIP = "data/oxford_robotcar/camera_health_development/centre_reference.mp4"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    cv2.setNumThreads(args.threads)
    capture, frames = cv2.VideoCapture(CLIP), []
    while len(frames) < args.frames + 5:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    runs = [objects.detect(f) for f in frames]
    times = [r["inference_ms"] for r in runs[5:]]   # first calls warm the engine
    report = {"opencv": cv2.__version__, "engine": runs[0]["engine"], "machine": platform.machine(), "threads": args.threads,
              "frames": len(times), "median_ms": round(statistics.median(times), 2), "p95_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 2),
              "detections_per_frame": round(statistics.mean(len(r["objects"]) for r in runs[5:]), 2)}
    print(json.dumps(report))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
