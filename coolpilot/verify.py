"""Second-stage checks for an obstruction suspicion (active perception).

The always-on monitor only says "these tiles lost detail while the rest of the view kept it". That also
happens for reasons that are not the lens. Each tool measures one such reason on the moment in question:

    texture   - is the tile a scene that cannot show lens loss? Either it was never detailed (blank wall),
                or it now shows open sky: upper half, bright, unsaturated. A tree leaving the frame turns
                a detailed tile into sky; the lens did nothing. Axis's Image Health Analytics excludes
                such "unsuitable" scenes for the same reason. Limitation: a whitish film over sky is missed.
    objects   - is a road user covering the tile? (NanoDet on OpenCV 5's new DNN engine)
    motion    - optical flow in the tiles vs the rest over the last second; reported as evidence only.

Tools never see labels. rule_verdict() is the fixed baseline the LLM agent is measured against.
Limits are set a priori from the tool definitions, not fitted to held-out clips.
"""
import time

import cv2
import numpy as np

from . import objects as detector

LOW_TEXTURE = 0.15   # tile's normal detail below 15% of the camera's median tile: nothing to obstruct
SKY_BRIGHTNESS, SKY_SATURATION = 1.25, 20   # open sky: >= 1.25x the median tile brightness, HSV saturation <= 20
COVERED = 0.4        # road users cover at least 40% of the suspected tiles


def texture(frame_bgr, boxes, reference_detail, suspected: list[int]) -> dict:
    reference = np.asarray(reference_detail, dtype=float)
    median = float(np.median(reference)) or 1e-6
    relative = {int(i): round(float(reference[i]) / median, 3) for i in suspected}
    hsv = cv2.cvtColor(cv2.resize(frame_bgr, (320, 240), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2HSV)
    tiles = [hsv[int(y * 240):int((y + h) * 240), int(x * 320):int((x + w) * 320)] for x, y, w, h in boxes]
    value = np.array([t[..., 2].mean() for t in tiles]); median_value = float(np.median(value)) or 1e-6
    sky = {int(i): {"brightness": round(float(value[i]) / median_value, 2), "saturation": round(float(tiles[i][..., 1].mean()), 1)}
           for i in suspected}
    open_sky = [i for i, v in sky.items() if boxes[i][1] + boxes[i][3] <= 0.5
                and v["brightness"] >= SKY_BRIGHTNESS and v["saturation"] <= SKY_SATURATION]
    unsuitable = sorted({i for i, v in relative.items() if v < LOW_TEXTURE} | set(open_sky))
    return {"relative_texture": relative, "sky_now": sky, "open_sky_tiles": open_sky, "unsuitable_tiles": unsuitable,
            "limits": {"low_texture": LOW_TEXTURE, "sky_brightness": SKY_BRIGHTNESS, "sky_saturation": SKY_SATURATION}}


def road_users(frame_bgr, boxes: list[list[float]], suspected: list[int]) -> dict:
    if not detector.available():
        return {"error": "Detector model not installed (see data/models)."}
    found = detector.detect(frame_bgr)
    cover = {int(i): round(detector.coverage(found["objects"], boxes[i]), 3) for i in suspected}
    return {**found, "coverage": cover, "covered_fraction": round(float(np.mean(list(cover.values()))), 3) if cover else 0.0,
            "limit": COVERED}


def motion(frames_bgr: list, boxes: list[list[float]], suspected: list[int]) -> dict:
    """Median Farneback flow magnitude per tile between the first and last frame of the window."""
    if len(frames_bgr) < 2:
        return {"error": "Need at least two frames."}
    a, b = (cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (320, 240), interpolation=cv2.INTER_AREA) for f in (frames_bgr[0], frames_bgr[-1]))
    flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    magnitude = np.linalg.norm(flow, axis=2)
    per_tile = []
    for x, y, w, h in boxes:
        per_tile.append(float(np.median(magnitude[int(y * 240):int((y + h) * 240), int(x * 320):int((x + w) * 320)])))
    others = [v for i, v in enumerate(per_tile) if i not in suspected]
    rest = float(np.median(others)) if others else 0.0
    return {"tile_flow_px": {int(i): round(per_tile[i], 2) for i in suspected}, "other_tiles_median_px": round(rest, 2),
            "note": "A lens smudge is fixed to the camera; this is evidence for the reviewer, not a decision rule."}


def gather(frames_bgr, boxes, suspected, reference_detail) -> dict:
    start = time.process_time()
    evidence = {"texture": texture(frames_bgr[-1], boxes, reference_detail, suspected), "objects": road_users(frames_bgr[-1], boxes, suspected),
                "motion": motion(frames_bgr, boxes, suspected)}
    evidence["cpu_s"] = round(time.process_time() - start, 4)
    return evidence


def rule_verdict(evidence: dict, suspected: list[int]) -> dict:
    """Fixed baseline: dismiss only for a measured non-lens cause; otherwise keep the alarm."""
    unsuitable = evidence["texture"]["unsuitable_tiles"]
    if suspected and len(unsuitable) == len(suspected):
        return {"verdict": "dismiss", "reason": f"Suspected tiles {unsuitable} show scene that cannot reveal lens loss "
                                                 "(open sky now, or never detailed); the loss is the scene, not the lens."}
    covered = evidence["objects"].get("covered_fraction")
    if covered is not None and covered >= COVERED:
        users = sorted({o["label"] for o in evidence["objects"]["objects"]})
        return {"verdict": "dismiss", "reason": f"Road users ({', '.join(users)}) cover {covered:.0%} of the suspected tiles."}
    return {"verdict": "confirm", "reason": "No measured scene cause explains the local loss of detail."}


class ReplayVerifier:
    """Verifies each new obstruction episode of a running monitor in a background thread.

    dismiss -> the episode closes, is marked dismissed (not an alarm, not scored) and re-raising is
    suppressed until the condition clears. confirm, escalate or any error -> the alarm stands, counted
    from the verdict time. The analysis loop never waits for a verdict.
    """

    def __init__(self, mode: str, window_s: float = 1.0):
        from collections import deque
        from concurrent.futures import ThreadPoolExecutor
        self.mode, self.window_s = mode, window_s
        self.recent = deque()
        self.pool = ThreadPoolExecutor(max_workers=1) if mode != "off" else None
        self.pending, self.suppress, self.log = None, False, []

    def frame(self, time_s: float, frame_bgr):
        if self.mode == "off":
            return
        h, w = frame_bgr.shape[:2]
        self.recent.append((time_s, cv2.resize(frame_bgr, (640, round(h * 640 / w)), interpolation=cv2.INTER_AREA)))
        while self.recent and time_s - self.recent[0][0] > self.window_s:
            self.recent.popleft()

    def filter(self, local: set) -> set:
        if self.suppress:
            if "obstruction" in local:
                return local - {"obstruction"}
            self.suppress = False
        return local

    def _job(self, frames, boxes, tiles, reference):
        try:
            if self.mode == "agent":
                import asyncio
                from .verify_agent import investigate
                return asyncio.run(investigate(frames, boxes, tiles, reference))
            evidence = gather(frames, boxes, tiles, reference)
            return {**rule_verdict(evidence, tiles), "evidence": evidence, "tool_calls": ["texture", "objects", "motion"]}
        except Exception as error:   # noqa: BLE001 - a broken verifier must keep the alarm
            return {"verdict": "confirm", "reason": f"Verifier failed ({type(error).__name__}); alarm kept.", "error": True}

    def step(self, monitor, regions, now: float):
        if self.mode == "off":
            return
        episode = monitor.active.get("obstruction")
        if episode is not None and "verification" not in episode and self.pending is None and self.recent:
            tiles = [i for i, r in enumerate(regions) if r.get("suspected_obstruction")]
            episode["verification"] = {"status": "pending", "mode": self.mode, "requested_s": now, "tiles": tiles}
            self.pending = (self.pool.submit(self._job, [f for _, f in self.recent], [r["box"] for r in regions], tiles,
                                             monitor.recent_detail.tolist()), episode)
        if self.pending is not None and self.pending[0].done():
            future, episode = self.pending
            self.pending = None
            result = future.result()
            evidence = result.get("evidence") or {}
            found = evidence.get("objects", {}).get("objects") if isinstance(evidence.get("objects"), dict) else None
            counts = {} if found is not None else None
            for o in found or []:
                counts[o["label"]] = counts.get(o["label"], 0) + 1
            summary = {"objects": [f"{n} {label}" for label, n in sorted(counts.items(), key=lambda kv: -kv[1])] if counts is not None else None,
                       "engine": evidence.get("objects", {}).get("engine") if isinstance(evidence.get("objects"), dict) else None}
            episode["verification"].update(status="done", verdict=result["verdict"], reason=result["reason"], received_s=now,
                                           tool_calls=result.get("tool_calls"), summary=summary)
            self.log.append({"start_s": episode["start_s"], **episode["verification"]})
            if result["verdict"] == "dismiss":
                episode["end_s"], episode["dismissed"] = now, True
                monitor.active.pop("obstruction", None)
                monitor.clearing.pop("obstruction", None)
                monitor.pending.pop("obstruction", None)
                self.suppress = True
            else:
                episode["start_s"] = max(episode["start_s"], now)   # alarm counts from the verdict

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(wait=True)
