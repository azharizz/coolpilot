"""Calibrate on Oxford tuning clips AND DRIVE-C dev scenes together; validation splits are never read.

    python -m experiments.joint_calibrate --drivec ~/drivec/drivec_core_v1 --out results/joint.json

Oxford: the centre-camera tuning clips, scored by calibrate.evaluate (onset, recovery, false alarms).
DRIVE-C dev (S01-S05, daytime only): the drivec_eval onset protocol, clean clip then its corrupted
version. Pass = an alarm of the mapped class within 2 s after the join and none before it. Clean dev
clips alone: any alarm is a false alarm. Detector only (no verifier), so obstruction is judged strictly.

Selection: a candidate may not fail more Oxford tuning checks than --max-oxford-failed (0, like the defaults), apart from
--ignore-oxford-clip checks known to be uninformative; among those, fewest failed checks overall, then fewest false alarms,
then the smallest change from the defaults. DRIVE-C test (all night scenes) is validated
separately with drivec_eval --params, once.
"""
import argparse
import csv
import itertools
import json
import pickle
import sys
from multiprocessing import get_context
from pathlib import Path

import cv2

from coolpilot.camera_dataset import load
from coolpilot.camera_health import Monitor, analyze
from coolpilot.models import CameraThresholds
from experiments.calibrate import evaluate, measure
from experiments.drivec_eval import DETECT_S, OURS

GRID = {
    "glare_rise": [0.2, 0.25, 0.3],
    "glare_tiles": [1, 2],
    "dark_ratio": [0.55, 0.65, 0.75],
    "blur_ratio": [0.35, 0.5],
    "blur_quantile": [0.5, 0.35, 0.25],
    "obstruction_ratio": [0.35, 0.45],
    "obstruction_s": [0.5, 0.8],
    "hysteresis": [0.3, 0.5],
}
WIDTH = 640
CACHE = {}
OPTIONS = {}   # analyze() options for this round: the detail scale


def measure_clip(clip):
    return measure(clip, WIDTH, **OPTIONS)


def measure_file(path):
    capture = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        out.append(analyze(frame, WIDTH, **OPTIONS))
    capture.release()
    return out


def drivec_evaluate(thresholds):
    passed, failed, false_alarms, rows = 0, 0, 0, []
    for name, frames, join, want in CACHE["drivec"]:
        monitor = Monitor(thresholds)
        for i, measured in enumerate(frames):
            conditions, _ = monitor.appearance(measured, i / 30.0)
            monitor.update(conditions, i / 30.0, {})
        if want is None:   # a clean clip on its own
            false_alarms += len(monitor.episodes)
            rows.append({"clip": name, "alarms": [(e["type"], round(e["start_s"], 2)) for e in monitor.episodes]})
            continue
        before = [e for e in monitor.episodes if e["start_s"] < join]
        ok = not before and any(e["type"] == want and join <= e["start_s"] <= join + DETECT_S for e in monitor.episodes)
        passed += ok
        failed += not ok
        false_alarms += len(before)
        rows.append({"clip": name, "expected": want, "passed": ok, "before_join": [(e["type"], round(e["start_s"], 2)) for e in before]})
    return {"passed": passed, "failed": failed, "false_alarms": false_alarms, "clips": rows}


def run(params):
    thresholds = CameraThresholds(**params)
    oxford = evaluate(CACHE["oxford"], thresholds)
    drivec = drivec_evaluate(thresholds)
    return params, oxford, drivec


def summary(oxford, drivec):
    return {"oxford_failed": f"{oxford['failed_fault_checks']}/{oxford['fault_checks']}", "oxford_false_alarms": oxford["false_alarms"],
            "drivec_dev_passed": f"{drivec['passed']}/{drivec['passed'] + drivec['failed']}", "drivec_dev_false_alarms": drivec["false_alarms"]}


def measure_all(args, clips, clean, corrupted):
    with get_context("fork").Pool(args.workers) as pool:
        oxford = pool.map(measure_clip, clips)
        clean_frames = dict(zip(clean, pool.map(measure_file, clean.values())))
        bad_frames = pool.map(measure_file, [args.drivec / r["output_path"] for r in corrupted])
    CACHE["oxford"] = list(zip(clips, oxford))
    CACHE["drivec"] = [(clean[s].name, clean_frames[s], None, None) for s in clean] + [
        (r["sample_id"], clean_frames[r["scenario_id"]] + frames, len(clean_frames[r["scenario_id"]]) / 30.0, OURS[r["corruption_type"]])
        for r, frames in zip(corrupted, bad_frames)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drivec", type=Path, required=True)
    ap.add_argument("--oxford", default="oxford-camera-holdout")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cache", type=Path, help="pickle of the frame measurements; written once, reused by later rounds")
    ap.add_argument("--grid", type=Path, help="JSON grid for this round (default: GRID); unlisted keys keep their defaults")
    ap.add_argument("--detail-width", type=int, default=320)
    ap.add_argument("--max-oxford-failed", type=int, default=0, help="absolute guard; the frozen defaults fail 0/6")
    ap.add_argument("--ignore-oxford-clip", action="append", default=[],
                    help="exclude a check known to be uninformative from the guard (still reported), e.g. centre_obstruction")
    args = ap.parse_args()
    OPTIONS.update(detail_width=args.detail_width)
    grid = json.loads(args.grid.read_text()) if args.grid else GRID
    cv2.setNumThreads(1)
    clips = [c for c in load(args.oxford, verify=True)["clips"] if c["split"] == "tuning"]
    rows = list(csv.DictReader((args.drivec / "final_metadata.csv").open()))
    dev = {r["scenario_id"] for r in rows if r["is_clean"] == "1" and r["split"] == "dev"}
    clean = {s: sorted((args.drivec / "clean_clips").glob(f"{s}_*clean.mp4"))[0] for s in sorted(dev)}
    corrupted = [r for r in rows if r["is_clean"] != "1" and r["scenario_id"] in dev and OURS.get(r["corruption_type"])
                 and (args.drivec / r["output_path"]).is_file()]
    if args.cache and args.cache.is_file():
        CACHE.update(pickle.loads(args.cache.read_bytes()))   # our own measurements from an earlier round
    else:
        measure_all(args, clips, clean, corrupted)
        if args.cache:
            args.cache.write_bytes(pickle.dumps(CACHE))
    print(f"cached {len(clips)} Oxford tuning clips, {len(clean)} DRIVE-C dev scenes, {len(corrupted)} dev corruptions", file=sys.stderr)

    _, base_oxford, base_drivec = run({})
    print("defaults:", summary(base_oxford, base_drivec), file=sys.stderr, flush=True)
    keys = list(grid)
    combos = [dict(zip(keys, v)) for v in itertools.product(*grid.values())]
    with get_context("fork").Pool(args.workers) as pool:   # workers inherit CACHE
        results = pool.map(run, combos, chunksize=8)
    guarded = lambda oxford: sum(not c["passed"] for row in oxford["clips"] if row["clip"] not in args.ignore_oxford_clip for c in row["checks"])
    allowed = [r for r in results if guarded(r[1]) <= args.max_oxford_failed]
    defaults = CameraThresholds().model_dump()
    # Ties go to the candidate closest to the frozen defaults: the smallest change that achieves the score.
    change = lambda p: sum(abs(v - defaults[k]) / (abs(defaults[k]) or 1) for k, v in p.items())
    ranked = sorted(allowed, key=lambda r: (guarded(r[1]) + r[2]["failed"], r[1]["false_alarms"] + r[2]["false_alarms"], change(r[0])))
    if not ranked:
        sys.exit(f"No candidate keeps Oxford tuning at <= {args.max_oxford_failed} failed checks.")
    params, oxford, drivec = ranked[0]
    report = {"analyze_options": OPTIONS, "note": "Selected on Oxford tuning + DRIVE-C dev only. Validate with calibrate.py --split validation and drivec_eval.py --params.",
              "grid": grid, "candidates": len(combos), "guard_ignores": args.ignore_oxford_clip, "allowed_by_oxford_constraint": len(allowed),
              "defaults": {"thresholds": CameraThresholds().model_dump(), **summary(base_oxford, base_drivec),
                           "drivec": base_drivec, "oxford": base_oxford},
              "thresholds": params, "selected": {**summary(oxford, drivec), "drivec": drivec, "oxford": oxford},
              "top10": [{"thresholds": p, **summary(o, d)} for p, o, d in ranked[:10]]}
    print(json.dumps({"defaults": summary(base_oxford, base_drivec), "selected": summary(oxford, drivec), "thresholds": params}, indent=1))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, default=float) + "\n")


if __name__ == "__main__":
    main()
