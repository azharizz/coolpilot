"""Evaluate the frozen COOLPilot screen on DRIVE-C (independent: other country, camera and corruption code).

    python -m experiments.drivec_eval --root ~/drivec/drivec_core_v1 --out results/drivec.json

DRIVE-C clips (128 frames, 30 fps) are corrupted from their first frame. Two protocols:
    onset  - the scene's clean clip, then the corrupted clip: the fault starts at the join (our use case).
             Pass = an alarm of the mapped class starting within 2 s after the join, none before it.
    alone  - the corrupted clip by itself: a camera that starts broken; only absolute rules can fire.
Clean clips alone: any alarm is a false alarm. Thresholds: the frozen defaults, or --params (validation of a joint calibration).
"""
import argparse
import csv
import json
from collections import defaultdict
from itertools import chain
from pathlib import Path

import cv2

from coolpilot import footage
from coolpilot.models import CameraThresholds

OURS = {"defocus_blur": "blur", "motion_blur": "blur", "underexposure": "underexposure", "low_light": "underexposure",
        "glare_flare": "glare", "lens_occlusion": "obstruction"}
DETECT_S = 2.0


def frames(path):
    return footage.frames_of(cv2.VideoCapture(str(path)))


def count(path):
    capture = cv2.VideoCapture(str(path))
    n = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--params", type=Path, help="thresholds JSON (e.g. from joint_calibrate); default = frozen defaults")
    args = ap.parse_args()
    thresholds = CameraThresholds(**(json.loads(args.params.read_text())["thresholds"] if args.params else {}))
    rows = list(csv.DictReader((args.root / "final_metadata.csv").open()))
    clean = {}
    for scenario in sorted({r["scenario_id"] for r in rows}):
        found = sorted((args.root / "clean_clips").glob(f"{scenario}_*clean.mp4"))
        if found:
            clean[scenario] = found[0]
    meta = {r["scenario_id"]: r for r in rows if r["is_clean"] == "1"}
    results, table = [], defaultdict(lambda: {"onset_pass": 0, "alone_alarm": 0, "n": 0, "fired": defaultdict(int)})
    for scenario, path in clean.items():
        report = footage.screen(str(path), thresholds=thresholds)
        results.append({"clip": path.name, "kind": "clean", "split": meta.get(scenario, {}).get("split"),
                        "night": meta.get(scenario, {}).get("time_of_day") == "night",
                        "alarms": [(s["type"], s["start_s"]) for s in report["segments"]]})
    for r in rows:
        if r["is_clean"] == "1":
            continue
        path = args.root / r["output_path"]
        if not path.is_file() or r["scenario_id"] not in clean:
            continue
        base = clean[r["scenario_id"]]
        join = count(base) / 30.0
        joined = footage.screen_frames(chain(frames(base), frames(path)), 30.0, count(base) + count(path), thresholds=thresholds)
        alone = footage.screen(str(path), thresholds=thresholds)
        want = OURS.get(r["corruption_type"])
        before = [s for s in joined["segments"] if s["start_s"] < join]
        after = [s for s in joined["segments"] if join <= s["start_s"] <= join + DETECT_S]
        passed = want is not None and not before and any(s["type"] == want for s in after)
        key = (r["corruption_type"], int(r["severity_level"]))
        cell = table[key]
        cell["n"] += 1
        cell["onset_pass"] += passed
        cell["alone_alarm"] += bool(want and any(s["type"] == want for s in alone["segments"]))
        for s in after:
            cell["fired"][s["type"]] += 1
        results.append({"clip": r["sample_id"], "kind": "corrupted", "split": r["split"], "type": r["corruption_type"], "severity": int(r["severity_level"]),
                        "night": r["time_of_day"] == "night", "expected": want, "onset_pass": passed,
                        "before_join": [(s["type"], s["start_s"]) for s in before], "after_join": [(s["type"], s["start_s"]) for s in after],
                        "alone": [(s["type"], s["start_s"]) for s in alone["segments"]]})
        print(f"{r['sample_id']:28} expected={want or '-':13} onset={'PASS' if passed else '----'} after={[s['type'] for s in after]} alone={[s['type'] for s in alone['segments']]}", flush=True)
    summary = {f"{t}/s{s}": {"n": c["n"], "onset_pass": c["onset_pass"], "alone_alarm": c["alone_alarm"], "fired_after_join": dict(c["fired"])}
               for (t, s), c in sorted(table.items())}
    clean_rows = [r for r in results if r["kind"] == "clean"]
    by_split = {}
    for split in ("dev", "test"):
        ours = [r for r in results if r["kind"] == "corrupted" and r["split"] == split and r["expected"]]
        clean_split = [r for r in clean_rows if r["split"] == split]
        by_split[split] = {"our_classes_onset_pass": f"{sum(r['onset_pass'] for r in ours)}/{len(ours)}",
                           "clean_clips_with_alarm": f"{sum(bool(r['alarms']) for r in clean_split)}/{len(clean_split)}",
                           "joined_clips_alarming_before_onset": f"{sum(bool(r['before_join']) for r in results if r['kind'] == 'corrupted' and r['split'] == split)}/"
                                                                 f"{sum(1 for r in results if r['kind'] == 'corrupted' and r['split'] == split)}",
                           "night_scenes": sorted({r['clip'] for r in clean_split if r['night']})}
    report = {"dataset": "DRIVE-C core v1 (CC BY 4.0, doi:10.5281/zenodo.19656444)", "opencv": cv2.__version__, "thresholds": thresholds.model_dump(), "protocols": __doc__,
              "clean_clips_with_alarm": sum(bool(r["alarms"]) for r in clean_rows), "clean_clips": len(clean_rows), "by_split": by_split,
              "summary": summary, "clips": results}
    print(json.dumps({k: v for k, v in report.items() if k not in ("clips", "protocols")}, indent=1))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
