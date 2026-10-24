"""Local, content-locked recordings. Labels are returned only to the evaluator."""
import hashlib
import json
import re
from pathlib import Path

from .dataset import DATA, sha256
from .models import FAULTS


def media_path(folder: Path, name: str, suffix: str) -> Path:
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(suffix):
        raise ValueError("Media must be a local basename with the expected extension.")
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        raise ValueError("Media is absent or escapes its registered directory.")
    return path


def load(identifier: str, verify: bool = False) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", identifier):
        raise ValueError("Invalid dataset identifier.")
    folder = (DATA / "oxford_robotcar" / "camera_health_development" if identifier == "oxford-development"
              else DATA / "camera_health" / identifier)
    if not folder.resolve().is_relative_to(DATA.resolve()):
        raise ValueError("Dataset escapes the data directory.")
    path = media_path(folder, "manifest.json", ".json")
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported camera dataset schema.")
    artifacts = manifest["artifacts"]
    if not 1 <= len(artifacts) <= 64:
        raise ValueError("A dataset needs 1 to 64 clips.")
    digest = hashlib.sha256(raw)
    clips, groups, sources, ids = [], {}, {}, set()
    for artifact in artifacts:
        video = media_path(folder, artifact["file"], ".mp4")
        annotation = media_path(folder, artifact["annotation"], ".json")
        annotation_bytes = annotation.read_bytes()
        digest.update(annotation_bytes)
        item = json.loads(annotation_bytes)
        clip_id = video.stem
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", clip_id) or clip_id in ids:
            raise ValueError("Clip IDs must be unique safe basenames.")
        ids.add(clip_id)
        split = item["split"]
        group = item["split_group"]
        source = item["source_frames_sha256"]
        if split not in ("development_only", "tuning", "validation") or not group or not source:
            raise ValueError("Each clip needs explicit split, session group and source hash.")
        for key, mapping in ((group, groups), (item["session_id"], groups), (source, sources)):
            if key in mapping and mapping[key] != split:
                raise ValueError("A session or original recording crosses dataset splits.")
            mapping[key] = split
        times = item["relative_frame_timestamps_us"]
        if (not 2 <= len(times) <= 18000 or times[0] != 0
                or any(type(t) is not int for t in times)
                or any(b <= a for a, b in zip(times, times[1:]))
                or not 0 < times[-1] <= 600_000_000):
            raise ValueError("Expected increasing microsecond timestamps, at most 10 minutes per clip.")
        duration = times[-1] / 1e6 + (times[-1] - times[-2]) / 1e6
        events = []
        for event in item["events"]:
            kind = event["type"]
            start = event["first_affected_pts_us"] / 1e6
            end = event["first_recovered_pts_us"] / 1e6
            if kind not in FAULTS or not 0 <= start < end <= duration:
                raise ValueError("Invalid annotated event interval or type.")
            if event.get("provenance") not in ("synthetic_injection", "human_labelled_physical"):
                raise ValueError("Event provenance must be explicit.")
            if any(e["type"] == kind and e["end_s"] > start and e["start_s"] < end for e in events):
                raise ValueError("Same-class truth events must not overlap.")
            events.append({**event, "start_s": start, "end_s": end})
        expected = artifact["sha256"]
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("Missing media content hash.")
        if verify and sha256(video) != expected:
            raise ValueError("Video hash changed; regenerate the dataset manifest before running.")
        clips.append({"id": clip_id, "file": str(video), "sha256": expected,
                      "split": split, "session": item["session_id"], "group": group,
                      "camera": item["camera"], "source_sha256": source,
                      "timestamps_us": times, "duration_s": duration, "events": events})
    splits = {c["split"] for c in clips}
    if splits != {"development_only"} and not {"tuning", "validation"} <= splits:
        raise ValueError("Optimization datasets need disjoint tuning and validation sessions.")
    return {"id": identifier, "sha256": digest.hexdigest(), "development_only": splits == {"development_only"},
            "clips": clips, "schema_version": 1}


def public(dataset: dict) -> dict:
    return {**dataset, "clips": [{k: v for k, v in c.items() if k not in ("file", "timestamps_us", "events")}
                                  for c in dataset["clips"]]}


def catalog() -> list[dict]:
    ids = ["oxford-development"] + sorted(p.parent.name for p in (DATA / "camera_health").glob("*/manifest.json"))
    result = []
    for identifier in ids:
        try:
            result.append(public(load(identifier)))
        except (ValueError, KeyError, TypeError, OSError) as error:
            result.append({"id": identifier, "error": f"Dataset unavailable ({type(error).__name__})."})
    return result


def checked(settings, verify: bool = True) -> dict:
    dataset = load(settings.dataset, verify)
    if dataset["sha256"] != settings.dataset_sha256:
        raise ValueError("Dataset contract changed. Review and submit the current dataset hash.")
    clips = {c["id"]: c for c in dataset["clips"]}
    seen = set()
    for scenario in settings.scenarios:
        if scenario.clip not in clips or scenario.clip in seen:
            raise ValueError("Scenarios must name distinct registered clips.")
        seen.add(scenario.clip)
        intervals = list(scenario.interruptions)
        if scenario.processing_delay_interval:
            intervals.append(scenario.processing_delay_interval)
        if any(i.end_s > clips[scenario.clip]["duration_s"] for i in intervals):
            raise ValueError("Replay fault extends beyond the clip.")
        ordered = sorted(scenario.interruptions, key=lambda i: i.start_s)
        if any(a.end_s > b.start_s for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Interruption intervals overlap.")
    return dataset
