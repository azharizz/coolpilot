"""Build data/camera_health/drivec-sample: DRIVE-C clean clips plus our randomized faults on them.

    python3 scripts/generate_drivec_sample.py            # reads data/drivec_sample/original/*.mp4

Source: DRIVE-C core v1 (CC BY 4.0, doi:10.5281/zenodo.19656444), a few clean 4.3 s clips copied unmodified
into data/drivec_sample/original/ with the dataset's LICENSE, README and metadata. For every scene this
writes the original (hard-linked, byte-identical, as the reference clip) and six randomized fault clips
(blur, underexposure, glare, obstruction, blackout, freeze; short-clip recipes from camera_effects),
encoded H.264 CRF 23. DRIVE-C's own split is kept: dev scenes -> tuning, test scenes -> validation.
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coolpilot.simulation.camera_effects import KINDS, VERSION, effect, fields, random_recipe, strength  # noqa: E402

SOURCE = ROOT / "data" / "drivec_sample" / "original"
OUT = ROOT / "data" / "camera_health" / "drivec-sample"
NOTE = "DRIVE-C clean clip (CC BY 4.0) with synthetic COOLPilot faults; scenes are independent recordings"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encode(frames, path: Path, fps: float):
    h, w = frames[0].shape[:2]
    process = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                                "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
    for frame in frames:
        process.stdin.write(frame.tobytes())
    process.stdin.close()
    if process.wait():
        raise RuntimeError(f"ffmpeg failed for {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=4242)
    args = ap.parse_args()
    meta = {r["scenario_id"]: r for r in csv.DictReader((SOURCE / "final_metadata.csv").open()) if r["is_clean"] == "1"}
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    rng = np.random.default_rng(args.seed)
    artifacts = []
    for source in sorted(SOURCE.glob("S*_clean.mp4")):
        scene = source.name.split("_")[0]
        info = meta[scene]
        capture = cv2.VideoCapture(str(source))
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
        capture.release()
        h, w = frames[0].shape[:2]
        times_us = [round(i * 1e6 / fps) for i in range(len(frames))]
        duration = len(frames) / fps
        split = "tuning" if info["split"] == "dev" else "validation"
        session = f"drivec_{scene}"
        common = {"schema_version": 1, "recipe_version": VERSION, "session_id": session, "split_group": session, "split": split,
                  "camera": f"drivec/{info['scene_type']}_{info['time_of_day']}", "independence": NOTE,
                  "source": {"dataset": "DRIVE-C core v1", "doi": "10.5281/zenodo.19656444", "license": "CC BY 4.0",
                             "file": source.name, "scenario": scene, "time_of_day": info["time_of_day"],
                             "scene_type": info["scene_type"], "weather": info["weather"], "drivec_split": info["split"]},
                  "source_frames_sha256": sha256(source), "relative_frame_timestamps_us": times_us,
                  "randomized_seed": args.seed, "dimensions": [w, h]}
        for kind in KINDS:
            name = f"drivec_{scene.lower()}_{kind}"
            video = OUT / f"{name}.mp4"
            events = []
            if kind == "reference":
                os.link(source, video)   # the untouched original, byte-identical
            else:
                recipe = random_recipe(kind, duration, rng)
                masks = fields(h, w, recipe, kind)
                frozen, out, affected = None, [], []
                for i, frame in enumerate(frames):
                    t = times_us[i] / 1e6
                    if kind == "freeze" and frozen is None and strength(kind, t, recipe) > 0:
                        frozen = frames[i - 1] if i else frame
                    edited = effect(frame, kind, t, frozen, masks, recipe)
                    out.append(edited)
                    affected.append(strength(kind, t, recipe) > 0)
                encode(out, video, fps)
                first = affected.index(True)
                recovered = next(i for i in range(first, len(affected)) if not affected[i])
                events.append({"type": kind, "provenance": "synthetic_injection", "recipe": recipe,
                               "first_affected_pts_us": times_us[first], "first_recovered_pts_us": times_us[recovered],
                               "severity": "Parameters describe edit strength, not a validated detector threshold."})
            annotation = OUT / f"{name}.json"
            annotation.write_text(json.dumps({**common, "variant": kind, "events": events,
                                              "artifact": {"file": video.name, "sha256": sha256(video), "bytes": video.stat().st_size}}, indent=1) + "\n")
            artifacts.append({"variant": kind, "file": video.name, "sha256": sha256(video), "bytes": video.stat().st_size,
                              "annotation": annotation.name, "split": split, "scene": scene, "time_of_day": info["time_of_day"]})
            print(f"{name:34} {split:10} {video.stat().st_size / 1e6:5.1f} MB", flush=True)
    manifest = {"schema_version": 1, "dataset": "drivec-sample", "independence": NOTE,
                "source_url": "https://doi.org/10.5281/zenodo.19656444",
                "license_note": "DRIVE-C core v1, CC BY 4.0 (Shiva Aher, Georgia Institute of Technology). Attribution retained; faults added by COOLPilot.",
                "splits": {"tuning": "DRIVE-C dev scenes", "validation": "DRIVE-C test scenes (includes all night scenes)"},
                "artifacts": artifacts}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {OUT}: {len(artifacts)} clips, {sum(a['bytes'] for a in artifacts) / 1e6:.0f} MB (originals hard-linked)")


if __name__ == "__main__":
    main()
