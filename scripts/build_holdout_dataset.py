"""Assemble data/camera_health/oxford-camera-holdout from already generated clips.

    python3 scripts/build_holdout_dataset.py
    python3 scripts/build_holdout_dataset.py --name oxford-camera-holdout-fresh \
        --validation data/camera_health_build_fresh/*      # fresh seeds, never inspected while tuning

tuning     = the original centre-camera fixture (fixed 4-10 s faults), relabelled split "tuning"
validation = randomized faults on other cameras of the SAME drive (generated with --split validation --seed)

This is a camera-held-out split within one recorded drive. It is not an independent drive; the
manifest and every sidecar say so. Videos are hard-linked, never re-encoded, so hashes are preserved.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coolpilot.dataset import sha256  # noqa: E402

DATA = ROOT / "data"
TUNING = DATA / "oxford_robotcar" / "camera_health_development"
NOTE = "camera-held-out within one recorded drive, not an independent drive"


def link(src: Path, dst: Path):
    if dst.exists():
        dst.unlink()
    os.link(src, dst)


def add(folder: Path, annotation_name: str, relabel: bool, artifacts: list, OUT: Path):
    item = json.loads((folder / annotation_name).read_text())
    video = folder / item["artifact"]["file"]
    if relabel:
        session = item["session_id"].split("_centre")[0] + "_centre"
        item.update(split="tuning", session_id=session, split_group=session, independence=NOTE)
    link(video, OUT / video.name)
    (OUT / annotation_name).write_text(json.dumps(item, indent=2) + "\n")
    artifacts.append({"variant": item["variant"], "file": video.name, "sha256": item["artifact"]["sha256"],
                      "bytes": item["artifact"]["bytes"], "annotation": annotation_name, "events": item["events"],
                      "split": item["split"], "camera": item["camera"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="oxford-camera-holdout")
    ap.add_argument("--validation", nargs="+", type=Path,
                    default=[DATA / "camera_health_build" / name for name in ("left", "right", "rear")])
    args = ap.parse_args()
    OUT = DATA / "camera_health" / args.name
    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for name in sorted(p.name for p in TUNING.glob("centre_*.json")):
        add(TUNING, name, True, artifacts, OUT)
    for folder in args.validation:
        if not (folder / "manifest.json").exists():
            raise SystemExit(f"Missing {folder}; generate it first (see README).")
        for name in sorted(p.name for p in folder.glob("*_*.json")):
            add(folder, name, False, artifacts, OUT)
    for a in artifacts:
        assert sha256(OUT / a["file"]) == a["sha256"], a["file"]
    manifest = {"schema_version": 1, "dataset": args.name, "independence": NOTE,
                "source_url": "https://robotcar-dataset.robots.ox.ac.uk/downloads/sample.tar",
                "license_note": "Oxford RobotCar sample, CC BY-NC-SA terms; attribution retained; no commercial use inferred.",
                "splits": {"tuning": "stereo/centre, original fixed faults", "validation": "stereo/left, stereo/right, mono_rear, randomized faults"},
                "artifacts": artifacts}
    if args.name != "oxford-camera-holdout":   # keep the original manifest byte-identical (runs cite its hash)
        manifest["validation_sources"] = [str(f.resolve().relative_to(ROOT)) for f in args.validation]
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    counts = {}
    for a in artifacts:
        counts[a["split"]] = counts.get(a["split"], 0) + 1
    print(f"wrote {OUT} with {len(artifacts)} clips {counts}")


if __name__ == "__main__":
    main()
