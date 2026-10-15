"""Offline candidate measurements. Not imported by the application or a safety detector."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from coolpilot.benchmark import environment
from coolpilot.camera_health import Monitor, analyze
from coolpilot.models import CameraThresholds


class Candidate:
    def __init__(self, kind, *, tau_s=0.5, motion_px_s=5.0, persistence_s=1.0,
                 weights=None, brisque=None):
        if kind not in {"flow", "persistence", "ema", "spatial", "brisque"}:
            raise ValueError("Unknown candidate.")
        if any(not math.isfinite(v) or v <= 0 for v in (tau_s, motion_px_s, persistence_s)):
            raise ValueError("Time constants and motion threshold must be finite and positive.")
        self.weights = None
        if kind == "spatial":
            w = np.asarray(weights, dtype=float)
            if w.shape != (16,) or not np.isfinite(w).all() or np.any(w < 0) or not 0 < w.sum() < math.inf:
                raise ValueError("Spatial weighting requires 16 finite nonnegative weights with positive sum.")
            self.weights = w / w.sum()
        if kind == "brisque" and brisque is None:
            raise ValueError("BRISQUE needs cv2.quality plus model and range files.")
        self.kind, self.tau_s = kind, tau_s
        self.motion_px_s, self.persistence_s = motion_px_s, persistence_s
        self.brisque = brisque
        self.previous = self.time_s = self.ema = self.last_motion_s = None
        self.loss_since = np.full(16, np.nan)

    def measure(self, frame, measurements, time_s):
        if not math.isfinite(time_s) or time_s < 0 or (self.time_s is not None and time_s <= self.time_s):
            raise ValueError("Candidate requires finite, increasing source timestamps.")
        dt = None if self.time_s is None else time_s - self.time_s
        # Severity is an experimental feature, not a calibrated failure probability.
        severity = np.array([max(float(r["detail"] < 60), r["clipped"])
                             for r in measurements["regions"]])
        result = {}
        if self.kind == "ema":
            raw = float(severity.mean())
            self.ema = raw if dt is None else self.ema + (-math.expm1(-dt / self.tau_s)) * (raw - self.ema)
            result = {"raw_severity": raw, "smoothed_severity": self.ema}
        elif self.kind == "spatial":
            result = {"uniform_severity": float(severity.mean()),
                      "weighted_severity": float(self.weights @ severity)}
        elif self.kind == "brisque":
            image = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
            value = float(self.brisque.compute(image)[0])
            if not math.isfinite(value):
                raise ValueError("BRISQUE returned a nonfinite score.")
            result = {"brisque": value}
        else:
            gray = cv2.cvtColor(cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            motion = difference = None
            tracks = 0
            if self.previous is not None:
                difference = float(cv2.absdiff(gray, self.previous).mean())
                points = cv2.goodFeaturesToTrack(self.previous, 120, 0.01, 8)
                if points is not None:
                    forward, valid, _ = cv2.calcOpticalFlowPyrLK(self.previous, gray, points, None)
                    if forward is not None:
                        backward, back_valid, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous, forward, None)
                        if backward is not None:
                            good = ((valid.ravel() != 0) & (back_valid.ravel() != 0)
                                    & (np.linalg.norm((backward - points).reshape(-1, 2), axis=1) < 1))
                            tracks = int(good.sum())
                            if tracks >= 8:
                                motion = float(np.median(np.linalg.norm((forward - points).reshape(-1, 2)[good], axis=1)) / dt)
            moving = motion is not None and motion >= self.motion_px_s
            repeated = difference is not None and difference <= 0.3
            recent_motion = self.last_motion_s is not None and time_s - self.last_motion_s <= self.persistence_s
            result = {"tracked_points": tracks, "motion_px_s": motion, "difference": difference,
                      "repeated_imagery": repeated,
                      "repeat_after_motion": bool(repeated and recent_motion),
                      "motion_evidence": "unknown" if motion is None else "moving" if moving else "low_motion"}
            if self.kind == "persistence":
                loss = np.array([r.get("suspected_obstruction", False) for r in measurements["regions"]])
                # Only accumulate continuous, lens-coordinate detail loss with measured scene motion.
                eligible = loss & moving
                self.loss_since[~eligible] = np.nan
                self.loss_since[eligible & np.isnan(self.loss_since)] = time_s
                result["persistent_loss_tiles"] = np.flatnonzero(time_s - self.loss_since >= self.persistence_s).tolist()
            if moving:
                self.last_motion_s = time_s
            self.previous = gray
        self.time_s = time_s
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--candidate", choices=["flow", "persistence", "ema", "spatial", "brisque"], required=True)
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument("--max-frames", type=int, default=0, help="0 reads through EOF")
    parser.add_argument("--tau-s", type=float, default=0.5)
    parser.add_argument("--motion-px-s", type=float, default=5)
    parser.add_argument("--persistence-s", type=float, default=1)
    parser.add_argument("--weights", type=Path, help="JSON array, 16 row-major task-defined weights")
    parser.add_argument("--brisque-model", type=Path)
    parser.add_argument("--brisque-range", type=Path)
    args = parser.parse_args()
    if args.sample_every < 1 or args.max_frames < 0:
        parser.error("sample-every must be positive and max-frames nonnegative")
    brisque = None
    if args.candidate == "brisque":
        if not hasattr(cv2, "quality") or not args.brisque_model or not args.brisque_range:
            parser.error("BRISQUE requires cv2.quality and --brisque-model / --brisque-range; do not replace the main cv2 wheel")
        brisque = cv2.quality.QualityBRISQUE_create(str(args.brisque_model), str(args.brisque_range))
    if (args.weights is not None) != (args.candidate == "spatial"):
        parser.error("--weights is required only for the spatial candidate")
    weights = json.loads(args.weights.read_text()) if args.weights else None
    candidate = Candidate(args.candidate, tau_s=args.tau_s, motion_px_s=args.motion_px_s,
                          persistence_s=args.persistence_s, weights=weights, brisque=brisque)
    with args.video.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise ValueError("Cannot open video.")
    thresholds = CameraThresholds()
    monitor = Monitor(thresholds)
    cv2.setNumThreads(1)
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    print(json.dumps({"type": "metadata", "environment": environment(), "config": config,
                      "video_sha256": digest, "thresholds": thresholds.model_dump(),
                      "warning": "Offline unpaced measurements; no accuracy, capacity or safety claim."}))
    processed = index = 0
    last_pts = None
    total_base = total_candidate = 0.0
    try:
        while not args.max_frames or processed < args.max_frames:
            ok, frame = capture.read()
            if not ok:
                break
            pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if not math.isfinite(pts) or pts < 0 or (last_pts is not None and pts <= last_pts):
                raise ValueError("Decoder must provide strictly increasing source PTS; no synthetic clock fallback.")
            last_pts = pts
            index += 1
            if (index - 1) % args.sample_every:
                continue
            started = perf_counter()
            measurements = analyze(frame, 320)
            conditions, _ = monitor.appearance(measurements, pts)
            monitor.update(conditions, pts, {})
            baseline_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            features = candidate.measure(frame, measurements, pts)
            candidate_ms = (perf_counter() - started) * 1000
            total_base += baseline_ms
            total_candidate += candidate_ms
            processed += 1
            print(json.dumps({"type": "frame", "frame": index - 1, "pts_s": pts,
                              "baseline_conditions": sorted(conditions), "baseline_active": sorted(monitor.active),
                              "candidate": features, "baseline_ms": baseline_ms,
                              "candidate_extra_ms": candidate_ms}, allow_nan=False))
        if not processed:
            raise ValueError("Video produced no analyzed frames.")
        print(json.dumps({"type": "complete", "processed": processed,
                          "baseline_mean_ms": total_base / processed,
                          "candidate_extra_mean_ms": total_candidate / processed}))
    finally:
        capture.release()


if __name__ == "__main__":
    main()
