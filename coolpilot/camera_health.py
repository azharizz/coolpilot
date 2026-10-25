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


def analyze(frame, width: int, detail_width: int = 640) -> dict:
    height, original_width = frame.shape[:2]
    # Detail is always measured at detail_width (640, chosen in joint tuning); a smaller analysis width
    # would only be upscaled again, so it is raised to that scale rather than redefining calibration.
    width = max(width, detail_width)
    image = cv2.resize(frame, (width, round(height * width / original_width)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Compare detail at a common scale so a resolution change does not redefine calibration.
    # detail_width: the scale detail is measured at; defocus mostly removes fine detail, which a 320-wide
    # image has lost already (DRIVE-C paired analysis). A fixed 4:3 grid keeps calibration source-independent.
    w = detail_width
    gray = cv2.resize(gray, (w, w * 3 // 4), interpolation=cv2.INTER_AREA)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F)
    th, tw = gray.shape[0] // 4, w // 4
    # Tile statistics stay inside OpenCV so an accelerated build (e.g. COOL) covers them too.
    bright = cv2.compare(gray, 250, cv2.CMP_GE)
    regions = []
    for y in range(4):
        for x in range(4):
            rows, cols = slice(y * th, (y + 1) * th), slice(x * tw, (x + 1) * tw)
            _, deviation = cv2.meanStdDev(laplacian[rows, cols])
            regions.append({"box": [x / 4, y / 4, 0.25, 0.25], "mean": cv2.mean(gray[rows, cols])[0],
                            "detail": float(deviation[0, 0]) ** 2,
                            "clipped": cv2.countNonZero(bright[rows, cols]) / (th * tw)})
    return {"regions": regions, "black_fraction": cv2.countNonZero(cv2.compare(gray, 8, cv2.CMP_LT)) / gray.size,
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
    """Per-camera appearance rules. Each camera is compared with its own recent normal.

    Absolute limits alone mis-fire on real scenes (a bright sky is always clipped), so the
    main rules are relative to per-tile references learned while the camera looks healthy.
    """

    def __init__(self, thresholds: CameraThresholds):
        self.thresholds = thresholds
        self.previous = None
        self.reference_detail = None
        self.reference_mean = None
        self.reference_clipped = None
        self.recent_detail = None
        self.low_since = None
        self.spread = {"dark": 0.0, "blur": 0.0}   # this camera's normal swing of each log ratio while healthy
        self.signals = None
        self.spread_samples = 0
        self.dark_since_start = True
        self.frozen_since = None
        self.reference_time_s = None
        self.started_s = None
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
        means = np.array([r["mean"] for r in regions], dtype=float)
        clipped = np.array([r["clipped"] for r in regions], dtype=float)
        if self.started_s is None:
            self.started_s = time_s
        warm = time_s - self.started_s >= t.warmup_s
        conditions = set()
        # Absolute rules: valid without any reference (a camera that starts broken).
        blackout = measurements["black_fraction"] >= t.black_fraction
        if blackout:
            conditions.add("blackout")
        dark = float(means.mean()) < t.dark_mean
        self.dark_since_start = self.dark_since_start and dark
        # A camera dark since its first frame is ambiguous (night, or broken from power-on). With
        # dark_at_start_alarm off it is treated as its own normal; the relative rules still apply.
        absolute = t.dark_at_start_alarm or not self.dark_since_start
        if dark and absolute:
            conditions.add("underexposure")
        if np.mean(detail < t.blur_variance) >= 0.75 and absolute:
            conditions.add("blur")
        affected = np.zeros(len(regions), dtype=bool)
        low = affected
        if self.reference_detail is not None:
            elapsed = time_s - self.reference_time_s
            self.reference_detail *= math.exp(-elapsed / t.reference_decay_s)
            ratio = detail / np.maximum(self.recent_detail, 1e-6)
            self.signals = {"dark": math.log(max(float(means.mean()), 1e-6) / max(float(self.reference_mean.mean()), 1e-6)),
                            "blur": math.log(max(float(np.quantile(ratio, t.blur_quantile)), 1e-6))}
            if warm:
                # Relative rules against this camera's own references. Hysteresis: an active alarm
                # stays on until the signal is well back inside normal, so a fading fault is not
                # declared recovered while it is still visible.
                on = lambda kind, limit: 1 - (1 - limit) * t.hysteresis if kind in self.active else limit
                # Self-calibrating limits: a drop must exceed adaptive_k times this camera's own normal swing,
                # and at least a minimum effect. A busy scene widens its band; a calm one narrows it.
                limit = lambda kind, fixed, floor: (math.exp(-max(t.adaptive_k * self.spread[kind], floor)) if t.adaptive_k else fixed)
                dark_limit = limit("dark", t.dark_ratio, t.adaptive_floor_dark)
                blur_limit = limit("blur", t.blur_ratio, t.adaptive_floor_blur)
                if float(means.mean()) < on("underexposure", dark_limit) * float(self.reference_mean.mean()):
                    conditions.add("underexposure")
                rise = clipped - self.reference_clipped >= (t.glare_rise * t.hysteresis if "glare" in self.active else t.glare_rise)
                if int(rise.sum()) >= t.glare_tiles:   # one sky tile drifting against a frozen reference must not hold it on
                    conditions.add("glare")
                # Detail is compared with its recent healthy average, not the all-time peak: a
                # building that has passed must not make the open road look obstructed.
                if float(np.quantile(ratio, t.blur_quantile)) < on("blur", blur_limit):
                    conditions.add("blur")
                # Obstruction sits on the lens: the SAME tiles stay low while the rest of the view
                # keeps its detail. A passing scene moves across tiles and resets this clock.
                low = ratio < (1 - (1 - t.obstruction_ratio) * t.obstruction_hysteresis if "obstruction" in self.active else t.obstruction_ratio)
                if self.low_since is None:
                    self.low_since = np.full(len(regions), np.nan)
                if conditions or (set(self.active) - {"obstruction"}):
                    low = np.zeros(len(regions), dtype=bool)   # local loss only counts while the view is otherwise healthy
                self.low_since[~low] = np.nan
                self.low_since[low & np.isnan(self.low_since)] = time_s
                affected = low & (time_s - np.nan_to_num(self.low_since, nan=time_s) >= t.obstruction_s)
                others = ratio[~low]
                if 1 <= int(affected.sum()) <= t.obstruction_max_tiles and (not len(others) or float(np.median(others)) >= t.scene_keep_ratio):
                    conditions.add("obstruction")
                else:
                    affected[:] = False
            self.reference_detail = np.maximum(self.reference_detail, detail)
        else:
            self.reference_detail = detail.copy()
        for region, changed in zip(regions, affected):
            region["suspected_obstruction"] = bool(changed)
        # One cause explains the others: a black frame has no detail; a dark frame looks soft.
        if blackout:
            conditions &= {"blackout"}
        if "underexposure" in conditions:
            conditions.discard("blur")
            conditions.discard("obstruction")
        if "glare" in conditions or "glare" in self.active:
            conditions.discard("obstruction")   # washed-out highlights also lose local detail
        # A global fault (blackout, blur, dark, glare, freeze) just ended after a long freeze of the
        # references: the scene has moved on, so re-learn from this view before judging local loss.
        rebaseline = (warm and self.frozen_since is not None and time_s - self.frozen_since > min(t.reference_window_s, 1.5)
                      and not (conditions - {"obstruction"}) and not (set(self.active) - {"obstruction"}))
        if rebaseline:
            conditions.discard("obstruction")
            if self.low_since is not None:
                self.low_since[:] = np.nan
            for region in regions:
                region["suspected_obstruction"] = False
        # Brightness and clipping references only learn while the view looks healthy, so a
        # developing fault is never absorbed into "normal".
        if self.reference_mean is None:
            self.reference_mean, self.reference_clipped, self.recent_detail = means.copy(), clipped.copy(), detail.copy()
        else:
            k = -math.expm1(-(time_s - self.reference_time_s) / t.reference_window_s)
            local = (conditions | set(self.pending) | set(self.active)) <= {"obstruction"}
            if rebaseline:
                k, keep = 1.0, np.ones(len(regions), dtype=bool)
                self.frozen_since = None
            elif not warm or not (conditions or self.pending or self.active):
                if self.frozen_since is not None and time_s - self.frozen_since > min(t.reference_window_s, 1.5):
                    k = 1.0   # after a long fault the scene has moved on: re-learn from the current view
                self.frozen_since = None
                keep = np.ones(len(regions), dtype=bool)
                if self.signals:
                    # Learn the swing while healthy, warm-up included; a running mean until the window fills,
                    # so a short recording still learns its own band.
                    self.spread_samples += 1
                    a = max(-math.expm1(-(time_s - self.reference_time_s) / t.adaptive_window_s), 1 / self.spread_samples)
                    for kind, value in self.signals.items():
                        self.spread[kind] += a * (abs(value) - self.spread[kind])
            elif local:
                # A local suspicion only freezes the suspected tiles; the rest of the view keeps
                # learning, so a scene-driven false alarm cannot sustain itself.
                keep = ~(low if warm and self.low_since is not None else affected)
            else:
                keep = np.zeros(len(regions), dtype=bool)
                if self.frozen_since is None:
                    self.frozen_since = time_s
            if local and not rebaseline:
                # Suspected tiles still re-learn, only slowly: a lasting smudge stays flagged for many
                # seconds, but a scene change that merely looks like one fades instead of sticking forever.
                slow = -math.expm1(-(time_s - self.reference_time_s) / (4 * t.reference_window_s))
                rate = np.where(keep, k, slow)
            else:
                rate = k * keep
            self.reference_mean += rate * (means - self.reference_mean)
            self.reference_clipped += rate * (clipped - self.reference_clipped)
            self.recent_detail += rate * (detail - self.recent_detail)
        self.reference_time_s = time_s
        image = measurements["thumbnail"]
        if self.previous is not None:
            difference = float(cv2.absdiff(image, self.previous).mean())
            if difference <= t.freeze_difference and not blackout:
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
