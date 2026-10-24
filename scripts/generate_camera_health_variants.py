"""Create development-only Oxford centre-camera fault videos. No detector/model calls.

Requires OpenCV, NumPy, ffmpeg and ffprobe. Run with --self-check for the small
boundary/placement check; defaults preserve the original Bayer frames and timing.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coolpilot.simulation.camera_effects import VERSION, SEED, START, END, KINDS, PARAMETERS, strength, fields, effect, params, random_recipe, window

# Oxford RobotCar sample cameras: folder, timestamp file, Bayer pattern, short name.
CAMERAS = {
    "stereo/centre": ("stereo/centre", "stereo.timestamps", cv2.COLOR_BayerGBRG2BGR, "centre"),
    "stereo/left": ("stereo/left", "stereo.timestamps", cv2.COLOR_BayerGBRG2BGR, "left"),
    "stereo/right": ("stereo/right", "stereo.timestamps", cv2.COLOR_BayerGBRG2BGR, "right"),
    "mono_left": ("mono_left", "mono_left.timestamps", cv2.COLOR_BayerRGGB2BGR, "mono_left"),
    "mono_right": ("mono_right", "mono_right.timestamps", cv2.COLOR_BayerRGGB2BGR, "mono_right"),
    "mono_rear": ("mono_rear", "mono_rear.timestamps", cv2.COLOR_BayerRGGB2BGR, "rear"),
}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()




def self_check():
    rng = np.random.default_rng(7)
    image = rng.integers(20, 235, (96, 128, 3), dtype=np.uint8)
    frozen = np.full_like(image, 51)
    masks = fields(*image.shape[:2])
    for kind in KINDS:
        for seconds in (0, START, END, END+1):
            # Abrupt conditions start exactly at START; ramped effects start at zero.
            if seconds == START and kind in ("freeze", "blackout"):
                continue
            assert np.array_equal(effect(image, kind, seconds, frozen, masks), image), (kind, seconds)
        if kind != "reference":
            changed = effect(image, kind, 7, frozen, masks)
            assert not np.array_equal(changed, image), kind
    assert np.array_equal(effect(image, "freeze", 5, frozen, masks), frozen)
    assert np.array_equal(effect(image, "freeze", 9, frozen, masks), frozen)
    assert not effect(image, "blackout", 7, frozen, masks).any()
    assert effect(image, "underexposure", 7, frozen, masks).mean() < image.mean() * 0.4
    obstruction = effect(image, "obstruction", 7, frozen, masks)
    assert np.array_equal(obstruction[masks["obstruction"][..., 0] == 0], image[masks["obstruction"][..., 0] == 0])
    assert strength("underexposure", END-0.5) < strength("underexposure", START+0.5)
    print("Boundary, recovery, blackout, freeze, exposure and fixed-region checks passed.", flush=True)


def encode(playlist, video):
    temporary = video.with_suffix(".encoding.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-n", "-f", "concat", "-safe", "0", "-i", str(playlist), "-an", "-c:v", "libx264", "-threads", "2", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-fps_mode", "vfr", "-enc_time_base", "1:1000000", "-video_track_timescale", "1000000", str(temporary)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-n", "-i", str(temporary), "-c", "copy", "-bsf:v", "h264_metadata=level=4:tick_rate=32:fixed_frame_rate_flag=0", "-movflags", "+faststart", str(video)], check=True)
    temporary.unlink()


def probe(video, relative_us, size):
    result = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time:stream=width,height,level:format=duration", "-of", "json", str(video)]))
    pts = [round(float(frame["best_effort_timestamp_time"])*1e6) for frame in result.pop("frames")]
    stream = result["streams"][0]
    if pts != relative_us or (stream["width"], stream["height"]) != size:
        raise ValueError(f"Video timing/dimension mismatch: {video}")
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(video), "-f", "null", "-"], check=True)
    return result


def generate(source, output, camera="stereo/centre", split="development_only", seed=None, tag=""):
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"Missing {executable}")
    folder, stamp_file, bayer, slug = CAMERAS[camera]
    timestamps_path = source / stamp_file
    timestamps = [int(line.split()[0]) for line in timestamps_path.read_text().splitlines()]
    if timestamps != sorted(set(timestamps)) or len(timestamps) < 100:
        raise ValueError("Expected an Oxford sample with increasing timestamps")
    relative_us = [value-timestamps[0] for value in timestamps]
    paths = [source / folder / f"{value}.png" for value in timestamps]
    expected = {path.name for path in paths}
    actual = {path.name for path in paths[0].parent.glob("*.png") if path.stem.isdigit()}
    if expected != actual or relative_us[-1] < 12_000_000:
        raise ValueError("Incomplete source recording")
    frame_hashes = {str(timestamp): sha256(path) for timestamp, path in zip(timestamps, paths)}
    source_identity = hashlib.sha256(json.dumps(frame_hashes, sort_keys=True).encode()).hexdigest()
    def decode(index):
        image = cv2.imread(str(paths[index]), cv2.IMREAD_UNCHANGED)
        if image is None or image.ndim != 2 or image.dtype != np.uint8:
            raise ValueError(f"Invalid Bayer image: {paths[index]}")
        return cv2.cvtColor(image, bayer)
    height, width = decode(0).shape[:2]
    duration_s = relative_us[-1] / 1e6
    # Seeded randomization: each fault gets its own onset, length, strength and position.
    rng = np.random.default_rng(seed) if seed is not None else None
    recipes = {kind: (random_recipe(kind, duration_s, rng) if rng is not None and kind != "reference" else None) for kind in KINDS}
    session = f"oxford_sample_{timestamps[0]}" + ("" if split == "development_only" else f"_{slug}")
    output.mkdir(parents=True, exist_ok=False)
    common = {
        "schema_version": 1, "recipe_version": VERSION, "seed": SEED,
        "session_id": session, "camera": camera,
        "split": split, "split_group": session,
        "independence": "development fixture" if split == "development_only" else "camera-held-out within one recorded drive, not an independent drive",
        "randomized_seed": seed,
        "source_url": "https://robotcar-dataset.robots.ox.ac.uk/downloads/sample.tar",
        "source_frames_sha256": source_identity, "timestamp_file_sha256": sha256(timestamps_path),
        "source_start_timestamp_us": timestamps[0], "relative_frame_timestamps_us": relative_us,
        "dimensions": [width, height], "nominal_rate_hz": 16,
        "timing": "Original relative timestamps, including 35 approximately 125ms intervals. These are not injected faults.",
        "codec": {"name": "H.264", "crf": 18, "preset": "medium", "threads": 2, "pixel_format": "yuv420p", "level": 4},
        "generator_sha256": sha256(Path(__file__)),
        "environment": {"opencv": cv2.__version__, "numpy": np.__version__, "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]},
        "limits": ["Synthetic edits, not physical fault validation.", "All sample cameras/variants belong to one development session; no independent held-out evidence.", "Reference means no injected edit, not a certified healthy feed.", "No detector, model, AWS, COOL or live capacity result is produced.", "Injection labels are evaluator-only; never pass recipes or labels to inference.", "No feed interruption/backlog is simulated by these MP4s.", "Retain Oxford RobotCar attribution and applicable CC BY-NC-SA terms; no commercial or public-sharing clearance inferred."],
    }
    artifacts = []
    with tempfile.TemporaryDirectory(prefix="coolpilot-health-frames-") as temporary:
        work = Path(temporary)
        for kind in KINDS:
            recipe = recipes[kind]
            start, end = window(recipe)
            frozen_index = max(i for i, value in enumerate(relative_us) if value/1e6 < start)
            frozen = decode(frozen_index)
            masks = fields(height, width, recipe, kind)
            frame_receipts = []
            concat = ["ffconcat version 1.0"]
            for index, (timestamp, microseconds) in enumerate(zip(timestamps, relative_us)):
                image = decode(index)
                rendered = effect(image, kind, microseconds/1e6, frozen, masks, recipe)
                changed = not np.array_equal(image, rendered)
                if not start <= microseconds/1e6 < end or kind == "reference":
                    assert not changed, (kind, timestamp)
                path = work / f"{timestamp}.png"
                if not cv2.imwrite(str(path), rendered, [cv2.IMWRITE_PNG_COMPRESSION, 1]):
                    raise RuntimeError(f"Could not write {path}")
                frame_receipts.append({"source_timestamp_us": timestamp, "pts_us": microseconds, "injected": changed, "strength": strength(kind, microseconds/1e6, recipe), "rgb_sha256": hashlib.sha256(cv2.cvtColor(rendered, cv2.COLOR_BGR2RGB).tobytes()).hexdigest()})
                concat.extend([f"file '{path}'", "option framerate 1000000"])
                if index+1 < len(timestamps):
                    concat.append(f"duration {(relative_us[index+1]-microseconds)/1e6:.6f}")
            playlist = work / "frames.ffconcat"
            playlist.write_text("\n".join(concat)+"\n")
            video = output / f"{slug}{tag}_{kind}.mp4"
            encode(playlist, video)
            verification = probe(video, relative_us, (width, height))
            changed_frames = [frame for frame in frame_receipts if frame["injected"]]
            event = []
            if changed_frames:
                event = [{"type": kind, "provenance": "synthetic_injection", "scheduled_interval_s": [start, end], "recipe": recipe, "first_affected_pts_us": changed_frames[0]["pts_us"], "first_recovered_pts_us": next(frame["pts_us"] for frame in frame_receipts if frame["pts_us"] > changed_frames[-1]["pts_us"]), "affected_frames": len(changed_frames), "parameters": params(kind, recipe), "coordinates": "normalized image coordinates; glare and obstruction stay camera-fixed", "severity": "Parameters describe edit strength, not a validated detector threshold."}]
                if kind == "freeze":
                    event[0]["frozen_source_timestamp_us"] = timestamps[frozen_index]
            annotation = {**common, "variant": kind, "events": event, "frames": frame_receipts, "artifact": {"file": video.name, "sha256": sha256(video), "bytes": video.stat().st_size}, "verification": verification}
            annotation_path = video.with_suffix(".json")
            annotation_path.write_text(json.dumps(annotation, indent=2)+"\n")
            artifacts.append({"variant": kind, **annotation["artifact"], "annotation": annotation_path.name, "events": event})
            print(json.dumps(artifacts[-1]), flush=True)
            for timestamp in timestamps:
                (work / f"{timestamp}.png").unlink()
    # Recheck sources after generation: the dataset must remain immutable.
    assert all(sha256(path) == frame_hashes[str(timestamp)] for timestamp, path in zip(timestamps, paths))
    (output / "manifest.json").write_text(json.dumps({**common, "source_frame_sha256": frame_hashes, "artifacts": artifacts}, indent=2)+"\n")
    print(f"Completed {len(artifacts)} videos in {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "data/oxford_robotcar")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--camera", choices=list(CAMERAS), default="stereo/centre")
    parser.add_argument("--split", choices=["development_only", "tuning", "validation"], default="development_only")
    parser.add_argument("--seed", type=int, help="randomize each fault's onset, length, strength and position")
    parser.add_argument("--tag", default="", help="clip-name suffix, e.g. _s1101, so several seeds of one camera can share a dataset")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        generate(args.source, args.output or args.source / "camera_health_development", args.camera, args.split, args.seed, args.tag)
