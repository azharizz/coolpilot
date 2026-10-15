"""A portable benchmark executable; each invocation owns its worker processes."""

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import resource
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter, process_time

import cv2
import numpy as np

from .dataset import clip, manifest
from .models import Configuration
from .tracking import STAGES, evaluate, track


def environment() -> dict:
    build = cv2.getBuildInformation()
    source = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source.update(path.name.encode())
        source.update(path.read_bytes())
    return {
        "runner_sha256": source.hexdigest(),
        "architecture": platform.machine(),
        "system": platform.system(),
        "cpu_count": len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else os.cpu_count(),
        "opencv_version": cv2.__version__,
        "opencv_path": cv2.__file__,
        "build_sha256": hashlib.sha256(build.encode()).hexdigest(),
        "opencv_build": build,
        "distribution": "COOL"
        if str(cv2.__file__).startswith("/opt/cool/")
        else "OpenCV",
        "hardware_note": "Measured on this host. Architecture alone does not establish Graviton performance.",
    }


def worker(
    config_data: dict,
    paths: list[str],
    truth: list,
    shape: tuple[int, int],
    repetitions: int,
    barrier,
) -> dict:
    try:
        config = Configuration.model_validate(config_data)
        ground_truth = np.asarray(truth, np.float32)
        track(paths[: min(len(paths), 20)], ground_truth[0], config)
        runs = []
        for _ in range(repetitions):
            barrier.wait()
            cpu_start = process_time()
            began = perf_counter()
            result = track(paths, ground_truth[0], config)
            ended = perf_counter()
            result["cpu_seconds"] = process_time() - cpu_start
            result["started"] = began
            result["ended"] = ended
            # Evaluation must not compete with another stream's timed tracking.
            barrier.wait()
            result["quality"] = evaluate(result["polygons"], ground_truth, *shape)
            runs.append(result)
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {
            "runs": runs,
            "peak_rss_mb": rss
            / (1024 * 1024 if platform.system() == "Darwin" else 1024),
        }
    except Exception:
        # Release sibling workers if decoding or OpenCV fails before a rendezvous.
        barrier.abort()
        raise


def benchmark(
    config: Configuration,
    split: str,
    frames: int,
    repetitions: int,
    hourly_price: float | None = None,
) -> dict:
    info = manifest()
    paths, truth = clip(split, frames)
    context = multiprocessing.get_context("spawn")
    # Separate processes are required: OpenCV's thread setting is process-global.
    with context.Manager() as manager:
        barrier = manager.Barrier(config.workers)
        with ProcessPoolExecutor(
            max_workers=config.workers, mp_context=context
        ) as pool:
            futures = [
                pool.submit(
                    worker,
                    config.model_dump(),
                    paths,
                    truth.tolist(),
                    (info["width"], info["height"]),
                    repetitions,
                    barrier,
                )
                for _ in range(config.workers)
            ]
            outputs = []
            try:
                for future in as_completed(futures):
                    outputs.append(future.result())
            except Exception:
                # A crashed worker cannot strand surviving workers at the barrier.
                barrier.abort()
                raise
    rows = [run for output in outputs for run in output["runs"]]
    rounds = []
    for i in range(repetitions):
        batch = [output["runs"][i] for output in outputs]
        wall = max(r["ended"] for r in batch) - min(r["started"] for r in batch)
        rounds.append(
            {
                "wall_seconds": wall,
                "throughput_fps": frames * config.workers / wall,
                "cpu_seconds": sum(r["cpu_seconds"] for r in batch),
                "p95_ms": float(
                    np.percentile([v for r in batch for v in r["latencies_ms"]], 95)
                ),
            }
        )
    total_wall = sum(r["wall_seconds"] for r in rounds)
    throughput = frames * config.workers * repetitions / total_wall
    latencies = [v for r in rows for v in r["latencies_ms"]]
    env = environment()
    metrics = {
        "throughput_fps": throughput,
        "p95_ms": float(np.percentile(latencies, 95)),
        "p50_ms": float(np.median(latencies)),
        # Conservative across repetitions and worker replicas: all must satisfy quality.
        "success_rate": min(r["quality"]["success_rate"] for r in rows),
        "corner_error_px": max(r["quality"]["corner_error_px"] for r in rows),
        "mean_iou": min(r["quality"]["mean_iou"] for r in rows),
        "lost_frames": max(r["quality"]["lost_frames"] for r in rows),
        "scored_frames_per_stream": frames - 1,
        "processed_frames_per_stream": len(rows[0]["latencies_ms"]),
        "prediction_interval_ms": 1000 * config.frame_stride / info["fps"],
        "cpu_capacity_pct": sum(r["cpu_seconds"] for r in rounds)
        / total_wall
        / env["cpu_count"]
        * 100,
        "worker_peak_rss_sum_mb": sum(o["peak_rss_mb"] for o in outputs),
        "cost_per_video_hour": hourly_price * info["fps"] / throughput
        if hourly_price is not None
        else None,
        "stages_ms": {
            s: float(np.mean([v for r in rows for v in r["stages_ms"][s]]))
            for s in STAGES
        },
    }
    exemplar = rows[0]
    return {
        "config": config.model_dump(),
        "split": split,
        "dataset_sha256": info["sha256"],
        "frames": frames,
        "repetitions": repetitions,
        "metrics": metrics,
        "rounds": rounds,
        "environment": env,
        "trace": {
            "polygons": exemplar["polygons"],
            "truth": truth.tolist(),
            "errors_px": exemplar["quality"]["errors_px"],
            "ious": exemplar["quality"]["ious"],
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", choices=("tuning", "validation"), default="tuning")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--hourly-price", type=float)
    args = parser.parse_args()
    configuration = Configuration.model_validate_json(args.config.read_text())
    if not 30 <= args.frames <= 1000 or not 1 <= args.repetitions <= 10:
        parser.error("Frames must be 30..1000 and repetitions 1..10.")
    print(
        json.dumps(
            benchmark(
                configuration,
                args.split,
                args.frames,
                args.repetitions,
                args.hourly_price,
            ),
            allow_nan=False,
        )
    )
