"""Image measurements and temporal episodes; no annotations enter this module."""
import math
import cv2
import numpy as np

from .models import CameraThresholds

OBSERVATIONS = {
    "blur": "low spatial detail",
    "underexposure": "low brightness",
    "glare": "highlight clipping",
    "obstruction": "regional detail loss",
    "blackout": "near-black imagery",
    "freeze": "repeated imagery",
}


def analyze(frame, width: int) -> dict:
    height, original_width = frame.shape[:2]
    image = cv2.resize(frame, (width, round(height * width / original_width)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Compare detail at a common scale so a resolution change does not redefine calibration.
    gray = cv2.resize(gray, (320, 240), interpolation=cv2.INTER_AREA)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F)
    regions = []
    for y in range(4):
        for x in range(4):
            tile = gray[y * 60:(y + 1) * 60, x * 80:(x + 1) * 80]
            regions.append({"box": [x / 4, y / 4, 0.25, 0.25], "mean": float(tile.mean()),
                            "detail": float(laplacian[y * 60:(y + 1) * 60, x * 80:(x + 1) * 80].var()),
                            "clipped": float(np.mean(tile >= 250))})
    return {"regions": regions, "black_fraction": float(np.mean(gray < 8)),
            "thumbnail": cv2.resize(gray, (80, 60), interpolation=cv2.INTER_AREA)}


def assess_health(*, unavailable: bool, stale: bool, delivery_conditions: set[str],
                  visual_conditions: set[str]) -> dict:
    """Source-independent health channels; no injection labels or remote scores.

    Pipeline health describes delivery/processing only. Visual rules are unvalidated
    suspicions, not camera-failure diagnoses or evidence that a scene is safe.
    Stale evidence cannot establish current image quality; retain prior suspicions.
    """
    return {
        "pipeline_status": "unavailable" if unavailable else "unknown" if stale else
                           "degraded" if delivery_conditions else "healthy",
        "quality_status": "unknown" if unavailable or stale else
                          "suspected" if visual_conditions else "no_issue_detected",
        "delivery_conditions": sorted(delivery_conditions),
        "visual_conditions": sorted(visual_conditions),
        "visual_observations": [OBSERVATIONS[k] for k in sorted(visual_conditions)],
    }


class Monitor:
    def __init__(self, thresholds: CameraThresholds):
        self.thresholds = thresholds
        self.previous = None
        self.reference_detail = None
        self.reference_time_s = None
        self.unchanged_since = None
        self.pending = {}
        self.clearing = {}
        self.active = {}
        self.episodes = []

    def appearance(self, measurements: dict, time_s: float) -> tuple[set[str], list[dict]]:
        t = self.thresholds
        if not math.isfinite(time_s) or time_s < 0 or (
            self.reference_time_s is not None and time_s <= self.reference_time_s
        ):
            raise ValueError("Appearance requires finite, increasing source timestamps.")
        regions = measurements["regions"]
        detail = np.array([r["detail"] for r in regions], dtype=float)
        means = np.array([r["mean"] for r in regions])
        conditions = set()
        if measurements["black_fraction"] >= t.black_fraction:
            conditions.add("blackout")
        if float(means.mean()) < t.dark_mean:
            conditions.add("underexposure")
        if any(r["clipped"] >= t.glare_fraction for r in regions):
            conditions.add("glare")
        if np.mean(detail < t.blur_variance) >= 0.75:
            conditions.add("blur")
        if self.reference_detail is not None:
            elapsed = time_s - self.reference_time_s
            self.reference_detail *= math.exp(-elapsed / t.reference_decay_s)
            affected = detail < self.reference_detail * t.obstruction_ratio
            # Regional loss is suspicion only; scenes and shadows can produce the same evidence.
            if 1 <= int(affected.sum()) <= 10:
                conditions.add("obstruction")
            for region, changed in zip(regions, affected):
                region["suspected_obstruction"] = bool(changed)
            self.reference_detail = np.maximum(self.reference_detail, detail)
        else:
            self.reference_detail = detail.copy()
        self.reference_time_s = time_s
        image = measurements["thumbnail"]
        if self.previous is not None:
            difference = float(cv2.absdiff(image, self.previous).mean())
            if difference <= t.freeze_difference:
                if self.unchanged_since is None:
                    self.unchanged_since = time_s
                if time_s - self.unchanged_since >= t.freeze_s:
                    conditions.add("freeze")
            else:
                self.unchanged_since = None
        self.previous = image
        return conditions, regions

    def update(self, conditions: set[str], time_s: float, evidence: dict):
        for kind in set(self.pending) | set(self.active) | conditions:
            if kind in conditions:
                self.clearing.pop(kind, None)
                self.pending.setdefault(kind, time_s)
                if kind not in self.active and time_s - self.pending[kind] >= self.thresholds.persistence_s:
                    episode = {"type": kind, "observation": OBSERVATIONS.get(kind, kind),
                               "start_s": time_s, "end_s": None, "evidence": evidence}
                    self.episodes.append(episode)
                    self.active[kind] = episode
            else:
                self.pending.pop(kind, None)
                if kind in self.active:
                    self.clearing.setdefault(kind, time_s)
                    if time_s - self.clearing[kind] >= self.thresholds.recovery_s:
                        self.active.pop(kind)["end_s"] = time_s
                        self.clearing.pop(kind)


def score(events: list[dict], episodes: list[dict], duration: float,
          unknown_intervals: list[dict] | None = None) -> dict:
    """Exact-type onset matching; uncertain visual intervals cannot earn event recall."""
    unknown_intervals = unknown_intervals or []
    used, matches = set(), []
    for event in sorted(events, key=lambda e: e["start_s"]):
        unknown = event["type"] not in {"interruption", "backlog"} and any(
            item["start_s"] < event["end_s"] and event["start_s"] < item["end_s"]
            for item in unknown_intervals
        )
        found = None if unknown else next(
            (i for i, alarm in enumerate(episodes) if i not in used
             and alarm["type"] == event["type"]
             and event["start_s"] <= alarm["start_s"] < event["end_s"]),
            None,
        )
        row = {**event, "detected": found is not None, "unknown_evidence": unknown,
               "detection_s": None, "recovery_s": None,
               "premature_clear": False, "failed_clear": True}
        if found is not None:
            used.add(found)
            alarm = episodes[found]
            row["detection_s"] = alarm["start_s"] - event["start_s"]
            row["premature_clear"] = alarm["end_s"] is not None and alarm["end_s"] < event["end_s"]
            row["failed_clear"] = alarm["end_s"] is None
            if not row["premature_clear"] and not row["failed_clear"]:
                row["recovery_s"] = alarm["end_s"] - event["end_s"]
        matches.append(row)
    intervals = sorted(
        [(e["start_s"], min(duration, e["end_s"])) for e in events]
        + [(item["start_s"], min(duration, item["end_s"] or duration)) for item in unknown_intervals]
    )
    occupied, end = 0.0, 0.0
    for start, stop in intervals:
        occupied += max(0, stop - max(start, end))
        end = max(end, stop)
    uncertain = lambda alarm: alarm["type"] not in {"interruption", "backlog"} and any(
        item["start_s"] <= alarm["start_s"] < (item["end_s"] or duration)
        for item in unknown_intervals
    )
    return {"matches": matches,
            "false_alarms": [a for i, a in enumerate(episodes) if i not in used and not uncertain(a)],
            "normal_seconds": max(0, duration - occupied), "duration_s": duration}


def gate(metrics: dict, goals) -> dict:
    checks = []

    def add(name, actual, operator, limit):
        passed = actual is not None and (actual >= limit if operator == ">=" else actual <= limit)
        checks.append({"metric": name, "actual": actual, "operator": operator,
                       "limit": limit, "passed": passed})

    # Every stream/repetition must pass. Zero events cannot silently pass a declared fault gate.
    for row in metrics["evaluations"]:
        prefix = f"{row['clip']} r{row['repetition'] + 1} s{row['stream'] + 1}: "
        for kind, values in row["by_fault"].items():
            if kind not in goals.faults:
                continue
            limit = goals.faults[kind]
            add(prefix + kind + " recall", values["recall"], ">=", limit.min_recall)
            add(prefix + kind + " detection seconds", values["detection_s"], "<=", limit.max_detection_s)
            add(prefix + kind + " recovery seconds", values["recovery_s"], "<=", limit.max_recovery_s)
            add(prefix + kind + " premature/uncleared", values["bad_recovery"], "<=", 0)
        add(prefix + "maximum source-schedule-to-result age seconds", row["max_age_s"], "<=", goals.max_age_s)
        add(prefix + "unknown evidence fraction", row["unknown_fraction"], "<=", goals.max_unknown_fraction)
        if row["review_required"]:
            add(prefix + "image-review coverage", row["review_coverage"], ">=",
                1 - goals.max_api_failure_fraction)
        add(prefix + "unfinished frames", row["unfinished_frames"], "<=", 0)
    for repetition in metrics["repetition_evidence"]:
        for kind, limit in goals.faults.items():
            add(f"r{repetition['repetition'] + 1}: {kind} event denominator",
                repetition["event_counts"].get(kind, 0), ">=", limit.min_events)
        add(f"r{repetition['repetition'] + 1}: normal seconds",
            repetition["normal_seconds"], ">=", goals.min_normal_seconds)
        add(f"r{repetition['repetition'] + 1}: false alarms/hour",
            repetition["false_alarms_per_hour"], "<=", goals.max_false_alarms_per_hour)
    if goals.max_cost_per_camera_hour is not None:
        add("Complete included cost/camera-hour", metrics["cost_per_camera_hour"],
            "<=", goals.max_cost_per_camera_hour)
    return {"passed": all(c["passed"] for c in checks), "checks": checks}
