"""Sparse optical flow with measured stages and no evaluation-truth access."""

from time import perf_counter

import cv2
import numpy as np

from .models import Configuration

STAGES = (
    "decode",
    "resize",
    "grayscale",
    "blur",
    "features",
    "optical_flow",
    "geometry",
)


def track(paths: list[str], initial_polygon: np.ndarray, config: Configuration) -> dict:
    cv2.setNumThreads(config.threads)
    cv2.setRNGSeed(42)
    cv2.ocl.setUseOpenCL(False)
    stages = {name: [] for name in STAGES}
    latencies, polygons = [], []
    previous_gray = previous_points = None
    polygon = None
    scale = None
    for index, path in enumerate(paths):
        if index % config.frame_stride:
            polygons.append(None if polygon is None else (polygon / scale).tolist())
            continue
        began = perf_counter()
        frame = cv2.imread(path)
        if frame is None:
            raise ValueError("A dataset frame could not be decoded.")
        decoded = perf_counter()
        height = round(frame.shape[0] * config.width / frame.shape[1])
        scale = np.array(
            [config.width / frame.shape[1], height / frame.shape[0]], np.float32
        )
        frame = cv2.resize(frame, (config.width, height), interpolation=cv2.INTER_AREA)
        resized = perf_counter()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        converted = perf_counter()
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        blurred = perf_counter()
        flow_end = geometry_end = blurred
        if index == 0:
            polygon = initial_polygon.copy() * scale
        elif (
            polygon is not None
            and previous_points is not None
            and len(previous_points) >= 4
        ):
            points, status, _ = cv2.calcOpticalFlowPyrLK(
                previous_gray,
                gray,
                previous_points,
                None,
                winSize=(21, 21),
                maxLevel=config.pyramid_levels,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
            )
            flow_end = perf_counter()
            good = status.ravel().astype(bool) & np.isfinite(points).all(axis=(1, 2))
            homography = None
            if np.count_nonzero(good) >= 4:
                homography, _ = cv2.findHomography(
                    previous_points[good],
                    points[good],
                    cv2.RANSAC,
                    3.0 * float(scale.min()),
                )
            if homography is None:
                polygon = None
            else:
                projected = cv2.perspectiveTransform(
                    polygon.reshape(-1, 1, 2), homography
                ).reshape(4, 2)
                # Reject degenerate geometry at the OpenCV output boundary.
                polygon = (
                    projected
                    if np.isfinite(projected).all() and cv2.isContourConvex(projected)
                    else None
                )
            geometry_end = perf_counter()
        else:
            polygon = None
        feature_start = perf_counter()
        previous_points = None
        if polygon is not None:
            region = np.zeros(gray.shape, dtype=np.uint8)
            # Clip rasterization coordinates, never the actual predicted polygon.
            cv2.fillConvexPoly(
                region, np.clip(polygon, -100000, 100000).astype(np.int32), 255
            )
            previous_points = cv2.goodFeaturesToTrack(
                gray,
                maxCorners=config.features,
                qualityLevel=0.01,
                minDistance=3,
                mask=region,
            )
        end = perf_counter()
        previous_gray = gray
        polygons.append(None if polygon is None else (polygon / scale).tolist())
        if index:
            latencies.append((end - began) * 1000)
            values = (
                decoded - began,
                resized - decoded,
                converted - resized,
                blurred - converted,
                end - feature_start,
                flow_end - blurred,
                geometry_end - flow_end,
            )
            for name, value in zip(STAGES, values):
                stages[name].append(value * 1000)
    return {
        "polygons": polygons,
        "latencies_ms": latencies,
        "stages_ms": stages,
    }


def evaluate(polygons: list, truth: np.ndarray, width: int, height: int) -> dict:
    """All source frames count, including held outputs and missing predictions."""
    errors, overlaps = [], []
    diagonal = float(np.hypot(width, height))
    failures = 0
    for predicted, target in zip(polygons[1:], truth[1:], strict=True):
        if predicted is None:
            errors.append(diagonal)
            overlaps.append(0.0)
            failures += 1
            continue
        p = np.asarray(predicted, dtype=np.float32)
        errors.append(
            float(np.minimum(np.linalg.norm(p - target, axis=1).mean(), diagonal))
        )
        if not cv2.isContourConvex(p):
            overlaps.append(0.0)
            failures += 1
            continue
        area, _ = cv2.intersectConvexConvex(p, target.astype(np.float32))
        union = abs(cv2.contourArea(p)) + abs(cv2.contourArea(target)) - area
        overlaps.append(float(np.clip(area / union, 0, 1)) if union > 0 else 0.0)
    return {
        "success_rate": float(np.mean(np.array(overlaps) >= 0.5)),
        "corner_error_px": float(np.mean(errors)),
        "mean_iou": float(np.mean(overlaps)),
        "lost_frames": failures,
        "scored_frames": len(errors),
        "errors_px": errors,
        "ious": overlaps,
    }
