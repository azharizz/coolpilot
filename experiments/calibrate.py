"""Calibrate the relative detector rules on TUNING clips only, then report.

    python -m experiments.calibrate --dataset oxford-development --split development_only --out calib.json
    python -m experiments.calibrate --dataset oxford-camera-holdout --split validation --params calib.json

Unpaced: every decoded frame is analysed once (OpenCV), cached, and the cheap alarm logic is replayed
for each threshold candidate. Scoring is the app's own score(): exact-type onset inside the labelled
interval, premature/uncleared recovery and false alarms. Delivery faults are out of scope here; the
paced benchmark measures those. Never pass --split validation together with a sweep.
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

import cv2

from coolpilot.camera_dataset import load
from coolpilot.camera_health import Monitor, analyze, score
from coolpilot.models import CameraThresholds

GRID = {
    "glare_rise": [0.25, 0.3],
    "glare_tiles": [2],
    "dark_ratio": [0.55, 0.65],
    "blur_ratio": [0.35],
    "obstruction_ratio": [0.35, 0.45],
    "scene_keep_ratio": [0.85],
    "obstruction_s": [0.5, 0.8],
    "reference_window_s": [3.0, 6.0],
    "warmup_s": [1.0],
    "hysteresis": [0.3, 0.4, 0.5],
    "obstruction_hysteresis": [0.5, 0.8, 1.0],
    "recovery_s": [0.3, 0.5],
}
LIMIT = {"max_detection_s": 2.0, "max_recovery_s": 2.0}


def measure(clip, width):
    """Decode a clip once; return [(pts_s, measurements)] for every frame."""
    capture = cv2.VideoCapture(clip["file"])
    frames = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append((capture.get(cv2.CAP_PROP_POS_MSEC) / 1000, analyze(frame, width)))
    finally:
        capture.release()
    return frames


def evaluate(cached, thresholds):
    """Per-clip results plus a single cost: failed fault checks first, then false alarms."""
    rows, failed, false_alarms, normal = [], 0, 0, 0.0
    for clip, frames in cached:
        monitor = Monitor(thresholds)
        for pts, measured in frames:
            conditions, _ = monitor.appearance(measured, pts)
            monitor.update(conditions, pts, {})
        end = frames[-1][0] if frames else 0.0
        truth = [e for e in clip["events"] if e["type"] not in ("interruption", "backlog")]
        scored = score(truth, monitor.episodes, clip["duration_s"])
        checks = []
        for m in scored["matches"]:
            ok = m["detected"] and m["detection_s"] is not None and m["detection_s"] <= LIMIT["max_detection_s"] \
                and m["recovery_s"] is not None and m["recovery_s"] <= LIMIT["max_recovery_s"] and not m["premature_clear"]
            checks.append({"type": m["type"], "detected": m["detected"], "detection_s": m["detection_s"],
                           "recovery_s": m["recovery_s"], "premature_clear": m["premature_clear"], "passed": ok})
            failed += not ok
        fa = [{"type": a["type"], "start_s": round(a["start_s"], 2)} for a in scored["false_alarms"]]
        false_alarms += len(fa); normal += scored["normal_seconds"]
        rows.append({"clip": clip["id"], "camera": clip["camera"], "checks": checks, "false_alarms": fa, "end_s": end})
    per_hour = false_alarms * 3600 / normal if normal else None
    return {"failed_fault_checks": failed, "fault_checks": sum(len(r["checks"]) for r in rows),
            "false_alarms": false_alarms, "false_alarms_per_hour": per_hour, "normal_seconds": normal, "clips": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="oxford-development")
    ap.add_argument("--split", default="development_only", choices=["development_only", "tuning", "validation"])
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--params", type=Path, help="evaluate these thresholds (JSON from a previous sweep) instead of sweeping")
    ap.add_argument("--defaults", action="store_true", help="evaluate the current CameraThresholds defaults")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.split == "validation" and not (args.params or args.defaults):
        ap.error("Sweeping on the validation split would leak it into calibration. Use --params or --defaults.")
    dataset = load(args.dataset, verify=True)
    clips = [c for c in dataset["clips"] if c["split"] == args.split]
    if not clips:
        ap.error(f"No {args.split} clips in {args.dataset}.")
    cv2.setNumThreads(1)
    cached = [(c, measure(c, args.width)) for c in clips]
    print(f"cached {sum(len(f) for _, f in cached)} frames from {len(clips)} {args.split} clips", file=sys.stderr)
    if args.params or args.defaults:
        chosen = json.loads(args.params.read_text())["thresholds"] if args.params else {}
        result = evaluate(cached, CameraThresholds(**chosen))
        report = {"dataset": args.dataset, "split": args.split, "thresholds": CameraThresholds(**chosen).model_dump(), "result": result}
    else:
        keys, best = list(GRID), None
        for values in itertools.product(*GRID.values()):
            params = dict(zip(keys, values))
            r = evaluate(cached, CameraThresholds(**params))
            cost = (r["failed_fault_checks"], r["false_alarms"])
            if best is None or cost < best[0]:
                best = (cost, params, r)
        cost, params, r = best
        report = {"dataset": args.dataset, "split": args.split, "grid": GRID, "thresholds": params, "result": r,
                  "note": "Selected on this split only. Report held-out numbers separately with --params."}
    res = report["result"]
    print(json.dumps({"split": args.split, "failed_fault_checks": f"{res['failed_fault_checks']}/{res['fault_checks']}",
                      "false_alarms": res["false_alarms"], "false_alarms_per_hour": res["false_alarms_per_hour"],
                      "thresholds": report["thresholds"] if not (args.params or args.defaults) else "given"}, indent=1))
    for row in res["clips"]:
        print(f"  {row['clip']:28} " + " ".join(f"{c['type']}:{'ok' if c['passed'] else 'MISS' if not c['detected'] else 'late/uncleared'}" for c in row["checks"])
              + (f"  false={[(f['type'], f['start_s']) for f in row['false_alarms']]}" if row["false_alarms"] else ""))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, default=float) + "\n")


if __name__ == "__main__":
    main()
