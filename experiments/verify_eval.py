"""Measure second-stage verification of obstruction suspicions (Recommendation 1).

    python -m experiments.verify_eval --dataset oxford-camera-holdout --split validation --arms none rule agent

For every clip the frozen monitor runs over every frame (unpaced, as experiments/calibrate.py). Each new
obstruction episode is a *suspicion*; an arm decides it from the frames of the preceding second:

    none   - every suspicion becomes an alarm (the monitor alone)
    rule   - verify.rule_verdict over the OpenCV tools (fixed baseline)
    agent  - the Nebius model calls the same tools and decides (confirm, dismiss or escalate)

A dismissed suspicion is removed; a real fault dismissed this way is a miss. A confirmed or escalated one
stays, with its start delayed by the measured verification time. A verifier error keeps the alarm.
Scoring is the app's own score(). Never tune limits on the split you report.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import cv2

from coolpilot import verify
from coolpilot.camera_dataset import load
from coolpilot.camera_health import Monitor, analyze, score
from coolpilot.models import CameraThresholds

WINDOW_S = 1.0
LIMIT = {"max_detection_s": 2.0, "max_recovery_s": 2.0}
# Alarm-delay curve: offline screening or CCTV can wait longer than an in-car warning (Axis uses up to minutes).
DELAYS = (2.0, 10.0, 60.0)


def suspicions(clip, width, thresholds):
    """Run the monitor; return (episodes, [suspicion]) with frame index, time, tiles and reference."""
    capture = cv2.VideoCapture(clip["file"])
    monitor, found, index = Monitor(thresholds), [], 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            before = len(monitor.episodes)
            conditions, regions = monitor.appearance(analyze(frame, width), pts)
            monitor.update(conditions, pts, {})
            for episode in monitor.episodes[before:]:
                if episode["type"] == "obstruction":
                    found.append({"episode": episode, "index": index, "time_s": pts,
                                  "tiles": [i for i, r in enumerate(regions) if r["suspected_obstruction"]],
                                  "boxes": [r["box"] for r in regions], "reference": monitor.recent_detail.tolist()})
            index += 1
    finally:
        capture.release()
    return monitor.episodes, found


def frames_before(path, index, fps):
    capture = cv2.VideoCapture(path)
    first = max(0, index - int(round(WINDOW_S * fps)))
    capture.set(cv2.CAP_PROP_POS_FRAMES, first)
    frames = []
    for _ in range(index - first + 1):
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    return frames


async def decide(arm, suspicion, frames):
    start = time.perf_counter()
    if arm == "none":
        return {"verdict": "confirm", "reason": "No verification.", "latency_s": 0.0}
    evidence = verify.gather(frames, suspicion["boxes"], suspicion["tiles"], suspicion["reference"])
    if arm == "rule":
        result = verify.rule_verdict(evidence, suspicion["tiles"])
    else:
        from coolpilot.verify_agent import investigate
        result = await investigate(frames, suspicion["boxes"], suspicion["tiles"], suspicion["reference"])
    return {**result, "latency_s": round(time.perf_counter() - start, 3), "tool_cpu_s": evidence["cpu_s"],
            "evidence": evidence if arm == "rule" else result.get("evidence")}


async def run_arm(arm, cached):
    rows, failed, false_alarms, normal, decisions = [], 0, 0, 0.0, []
    at_delay = {d: [0, 0] for d in DELAYS}
    for clip, episodes, found, fps in cached:
        kept = [e for e in episodes if e["type"] != "obstruction"]
        for suspicion in found:
            frames = frames_before(clip["file"], suspicion["index"], fps)
            outcome = await decide(arm, suspicion, frames)
            truth = next((e["type"] for e in clip["events"] if e["start_s"] <= suspicion["time_s"] <= e["end_s"] + LIMIT["max_recovery_s"]), "none")
            decisions.append({"clip": clip["id"], "time_s": round(suspicion["time_s"], 2), "tiles": suspicion["tiles"],
                              "truth_at_time": truth, "verdict": outcome["verdict"], "reason": outcome["reason"],
                              "latency_s": outcome["latency_s"], "tool_calls": outcome.get("tool_calls")})
            if outcome["verdict"] != "dismiss":   # confirm, escalate and errors keep the alarm (fail-safe)
                kept.append({**suspicion["episode"], "start_s": suspicion["episode"]["start_s"] + outcome["latency_s"]})
        scored = score([e for e in clip["events"] if e["type"] not in ("interruption", "backlog")], kept, clip["duration_s"])
        checks = []
        for m in scored["matches"]:
            ok = (m["detected"] and m["detection_s"] is not None and m["detection_s"] <= LIMIT["max_detection_s"]
                  and m["recovery_s"] is not None and m["recovery_s"] <= LIMIT["max_recovery_s"] and not m["premature_clear"])
            checks.append({"type": m["type"], "passed": ok})
            for d in DELAYS:
                at_delay[d][1] += 1
                at_delay[d][0] += bool(m["detected"] and m["detection_s"] is not None and m["detection_s"] <= d
                                       and m["recovery_s"] is not None and m["recovery_s"] <= d and not m["premature_clear"])
            failed += not ok
        fa = [{"type": a["type"], "start_s": round(a["start_s"], 2)} for a in scored["false_alarms"]]
        false_alarms += len(fa); normal += scored["normal_seconds"]
        rows.append({"clip": clip["id"], "checks": checks, "false_alarms": fa})
    by_type = {}
    for r in rows:
        for c in r["checks"]:
            t = by_type.setdefault(c["type"], [0, 0]); t[0] += c["passed"]; t[1] += 1
    latencies = [d["latency_s"] for d in decisions]
    return {"arm": arm, "failed_fault_checks": f"{failed}/{sum(len(r['checks']) for r in rows)}",
            "pass_by_fault": {k: f"{a}/{b}" for k, (a, b) in sorted(by_type.items())},
            "passed_at_delay_s": {f"{d:g}": f"{a}/{b}" for d, (a, b) in at_delay.items()},
            "false_alarms": false_alarms, "false_alarms_per_hour": round(false_alarms * 3600 / normal, 1) if normal else None,
            "suspicions": len(decisions), "dismissed": sum(d["verdict"] == "dismiss" for d in decisions),
            "escalated": sum(d["verdict"] == "escalate" for d in decisions),
            "max_latency_s": max(latencies, default=0.0), "decisions": decisions, "clips": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="oxford-camera-holdout")
    ap.add_argument("--split", default="validation", choices=["development_only", "tuning", "validation"])
    ap.add_argument("--arms", nargs="+", default=["none", "rule"], choices=["none", "rule", "agent"])
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--params", type=Path, help="thresholds JSON; default = the frozen CameraThresholds defaults")
    args = ap.parse_args()
    thresholds = CameraThresholds(**(json.loads(args.params.read_text())["thresholds"] if args.params else {}))
    dataset = load(args.dataset, verify=True)
    clips = [c for c in dataset["clips"] if c["split"] == args.split]
    cv2.setNumThreads(1)
    cached = []
    for clip in clips:
        capture = cv2.VideoCapture(clip["file"]); fps = capture.get(cv2.CAP_PROP_FPS) or 16; capture.release()
        episodes, found = suspicions(clip, args.width, thresholds)
        cached.append((clip, episodes, found, fps))
    print(f"{len(clips)} {args.split} clips, {sum(len(f) for *_, f, _ in cached)} obstruction suspicions", file=sys.stderr)
    report = {"dataset": args.dataset, "split": args.split, "opencv": cv2.__version__,
              "arms": [asyncio.run(run_arm(arm, cached)) for arm in args.arms]}
    for arm in report["arms"]:
        print(json.dumps({k: v for k, v in arm.items() if k not in ("decisions", "clips")}))
        for d in arm["decisions"]:
            print(f"   {d['clip']:24} t={d['time_s']:5} tiles={d['tiles']} truth={d['truth_at_time']:12} -> {d['verdict']}: {d['reason'][:110]}")
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, default=str) + "\n")


if __name__ == "__main__":
    main()
