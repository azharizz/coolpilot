"""Same-host OpenCV build comparison (e.g. standard wheel vs licensed COOL).

Run once per interpreter on the SAME host, then compare:

    python -m experiments.opencv_profile --flow --out standard.json
    /path/to/cool/python -m experiments.opencv_profile --flow --out cool.json
    python -m experiments.opencv_profile --compare standard.json cool.json

Unpaced, single-stream, offline. It splits CPU into decode, OpenCV analysis, Python alarm logic
and the optional optical-flow candidate, and records every detection so builds can be checked
for identical behaviour. It is not the paced app replay, a capacity test or a safety claim.
"""
import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from time import perf_counter, process_time

import cv2
import numpy as np

from coolpilot.camera_health import Monitor, analyze
from coolpilot.models import CameraThresholds
from coolpilot.runtime import environment
from experiments.camera_health import Candidate

VIDEOS = [f"data/oxford_robotcar/videos/stereo_{v}.mp4" for v in ("left", "centre", "right")]
STAGES = ("decode", "opencv_analysis", "python_alarms", "flow_candidate")
# Builds may round differently; beyond these the measurements are treated as changed.
TOLERANCE = {"mean": 1e-6, "detail_relative": 1e-5, "clipped": 0.0, "black_fraction": 0.0}


def profile_video(path: Path, width: int, flow: bool, record: bool) -> dict:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot open video: {path}")
    monitor, candidate = Monitor(CameraThresholds()), Candidate("flow") if flow else None
    cpu = dict.fromkeys(STAGES, 0.0)
    analysis_ms, frames, last_pts = [], [], None
    started_cpu, started_wall = process_time(), perf_counter()
    try:
        while True:
            t = process_time()
            ok, frame = capture.read()
            cpu["decode"] += process_time() - t
            if not ok:
                break
            pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if last_pts is not None and pts <= last_pts:
                raise ValueError("Decoder must provide strictly increasing PTS.")
            last_pts = pts
            t, w = process_time(), perf_counter()
            measured = analyze(frame, width)
            cpu["opencv_analysis"] += process_time() - t
            analysis_ms.append((perf_counter() - w) * 1000)
            t = process_time()
            conditions, _ = monitor.appearance(measured, pts)
            monitor.update(conditions, pts, {})
            cpu["python_alarms"] += process_time() - t
            motion = None
            if candidate:
                t = process_time()
                motion = candidate.measure(frame, measured, pts)
                cpu["flow_candidate"] += process_time() - t
            if record:
                frames.append({
                    "pts_s": round(pts, 6), "conditions": sorted(conditions),
                    "regions": [[r["mean"], r["detail"], r["clipped"]] for r in measured["regions"]],
                    "black_fraction": measured["black_fraction"],
                    **({"motion_evidence": motion["motion_evidence"], "repeat_after_motion": motion["repeat_after_motion"],
                        "motion_px_s": motion["motion_px_s"]} if motion else {}),
                })
    finally:
        capture.release()
    if not analysis_ms:
        raise ValueError(f"No frames decoded: {path}")
    total_cpu = process_time() - started_cpu
    return {"frames": len(analysis_ms), "cpu_s": cpu, "total_cpu_s": total_cpu,
            "other_cpu_s": max(0.0, total_cpu - sum(cpu.values())), "wall_s": perf_counter() - started_wall,
            "analysis_ms_p50": float(np.percentile(analysis_ms, 50)), "analysis_ms_p95": float(np.percentile(analysis_ms, 95)),
            "episodes": [{"type": e["type"], "start_s": round(e["start_s"], 6), "end_s": e["end_s"] and round(e["end_s"], 6)}
                         for e in monitor.episodes],
            "detections": frames}


def run(args) -> dict:
    cv2.setNumThreads(args.threads)
    cv2.ocl.setUseOpenCL(False)
    videos = {}
    for video in args.videos:
        path = Path(video)
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        runs = [profile_video(path, args.width, args.flow, record=i == 1) for i in range(args.repeat + 1)][1:]
        # First pass is a discarded warm-up; report the median of the measured repeats.
        median = lambda f: statistics.median(f(r) for r in runs)
        videos[path.name] = {
            "sha256": digest, "frames": runs[0]["frames"],
            "cpu_s": {s: median(lambda r, s=s: r["cpu_s"][s]) for s in STAGES},
            "other_cpu_s": median(lambda r: r["other_cpu_s"]), "total_cpu_s": median(lambda r: r["total_cpu_s"]),
            "wall_s": median(lambda r: r["wall_s"]),
            "analysis_ms_p50": median(lambda r: r["analysis_ms_p50"]), "analysis_ms_p95": median(lambda r: r["analysis_ms_p95"]),
            "repeat_total_cpu_s": [r["total_cpu_s"] for r in runs],
            "episodes": runs[0]["episodes"], "detections": runs[0]["detections"],
        }
    facts = {k: v for k, v in environment().items() if k != "opencv_build"}
    return {"schema": "coolpilot-opencv-profile/1", "environment": facts,
            "settings": {"width": args.width, "threads": args.threads, "repeat": args.repeat, "flow": args.flow,
                         "numpy": np.__version__, "python": sys.version.split()[0]},
            "note": "Unpaced offline analysis on one host. Totals are exact process CPU; stage splits are approximate because decoder threads can charge CPU to a neighbouring stage. Excludes the app's paced replay loop.",
            "videos": videos}


def compare(a: dict, b: dict) -> dict:
    """Speed per stage plus whether every measurement and alarm stayed the same."""
    shared = sorted(set(a["videos"]) & set(b["videos"]))
    if not shared:
        raise ValueError("The two profiles share no videos.")
    if any(a["videos"][v]["sha256"] != b["videos"][v]["sha256"] for v in shared):
        raise ValueError("Video bytes differ between profiles; comparison would be invalid.")
    if a["settings"]["width"] != b["settings"]["width"] or a["settings"]["threads"] != b["settings"]["threads"]:
        raise ValueError("Width and thread settings must match.")
    stages = {}
    for stage in (*STAGES, "other", "total"):
        pick = (lambda p, v: p["videos"][v]["total_cpu_s"]) if stage == "total" else \
               (lambda p, v: p["videos"][v]["other_cpu_s"]) if stage == "other" else \
               (lambda p, v, s=stage: p["videos"][v]["cpu_s"][s])
        x, y = sum(pick(a, v) for v in shared), sum(pick(b, v) for v in shared)
        if x or y:
            stages[stage] = {"a_cpu_s": x, "b_cpu_s": y, "speedup": x / y if y else None}
    drift = dict.fromkeys(TOLERANCE, 0.0)
    flow_drift, changed = 0.0, []
    for v in shared:
        fa, fb = a["videos"][v]["detections"], b["videos"][v]["detections"]
        if not fa or not fb:
            raise ValueError(f"{v}: a profile has no recorded detections; re-run it.")
        if len(fa) != len(fb):
            changed.append(f"{v}: decoded {len(fa)} vs {len(fb)} frames")
            continue
        for i, (x, y) in enumerate(zip(fa, fb)):
            ra, rb = np.array(x["regions"]), np.array(y["regions"])
            drift["mean"] = max(drift["mean"], float(np.abs(ra[:, 0] - rb[:, 0]).max()))
            drift["detail_relative"] = max(drift["detail_relative"], float((np.abs(ra[:, 1] - rb[:, 1]) / np.maximum(1, ra[:, 1])).max()))
            drift["clipped"] = max(drift["clipped"], float(np.abs(ra[:, 2] - rb[:, 2]).max()))
            drift["black_fraction"] = max(drift["black_fraction"], abs(x["black_fraction"] - y["black_fraction"]))
            if x["conditions"] != y["conditions"]:
                changed.append(f"{v} frame {i}: {x['conditions']} vs {y['conditions']}")
            if "motion_evidence" in x and "motion_evidence" in y:
                if (x["motion_evidence"], x["repeat_after_motion"]) != (y["motion_evidence"], y["repeat_after_motion"]):
                    changed.append(f"{v} frame {i}: flow {x['motion_evidence']} vs {y['motion_evidence']}")
                if x["motion_px_s"] is not None and y["motion_px_s"] is not None:
                    flow_drift = max(flow_drift, abs(x["motion_px_s"] - y["motion_px_s"]) / max(1.0, abs(x["motion_px_s"])))
        if a["videos"][v]["episodes"] != b["videos"][v]["episodes"]:
            changed.append(f"{v}: alarm episodes differ")
    within = all(drift[k] <= TOLERANCE[k] for k in TOLERANCE)
    return {"a": a["environment"], "b": b["environment"], "videos": shared, "stages": stages,
            "measurement_drift": drift, "measurement_tolerance": TOLERANCE, "flow_motion_relative_drift": flow_drift,
            "changed_detections": changed[:50], "changed_detection_count": len(changed),
            "identical_alarms": not changed, "measurements_within_tolerance": within}


def print_comparison(result: dict):
    label = lambda e: f"{e['distribution']} {e['opencv_version']} ({e['system']}/{e['architecture']})"
    print(f"A: {label(result['a'])}\nB: {label(result['b'])}\nVideos: {', '.join(result['videos'])}\n")
    print(f"{'stage':<18}{'A cpu s':>10}{'B cpu s':>10}{'A/B':>8}{'share of A':>12}")
    total = result["stages"]["total"]["a_cpu_s"]
    for stage, row in result["stages"].items():
        speed = f"{row['speedup']:.2f}x" if row["speedup"] else "—"
        print(f"{stage:<18}{row['a_cpu_s']:>10.3f}{row['b_cpu_s']:>10.3f}{speed:>8}{row['a_cpu_s'] / total * 100:>11.0f}%")
    print(f"\nAlarms identical: {result['identical_alarms']} ({result['changed_detection_count']} differences)")
    print(f"Measurements within tolerance: {result['measurements_within_tolerance']} {result['measurement_drift']}")
    for line in result["changed_detections"][:10]:
        print("  ", line)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("videos", nargs="*", default=VIDEOS)
    parser.add_argument("--width", type=int, default=640, choices=(320, 640, 960, 1280))
    parser.add_argument("--threads", type=int, default=1, choices=(1, 2, 4, 8))
    parser.add_argument("--repeat", type=int, default=3, help="measured repeats after one warm-up pass")
    parser.add_argument("--flow", action="store_true", help="also time the sparse optical-flow candidate")
    parser.add_argument("--out", type=Path, help="write the profile JSON here (refuses to overwrite)")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A.json", "B.json"))
    args = parser.parse_args()
    if args.compare:
        result = compare(*(json.loads(p.read_text()) for p in args.compare))
        print_comparison(result)
        if args.out:
            args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        sys.exit(0 if result["identical_alarms"] else 1)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if args.out and args.out.exists():
        parser.error("--out already exists; keep earlier evidence")
    result = run(args)
    text = json.dumps(result, allow_nan=False)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)
    for name, video in result["videos"].items():
        stages = ", ".join(f"{s} {video['cpu_s'][s]:.2f}s" for s in STAGES if video["cpu_s"][s])
        print(f"{name}: {video['frames']} frames, total {video['total_cpu_s']:.2f}s CPU ({stages}, other {video['other_cpu_s']:.2f}s)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
