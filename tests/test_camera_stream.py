import unittest
from concurrent.futures import Future
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from coolpilot.simulation import camera_benchmark, camera_comparison
from coolpilot.simulation.camera_benchmark import ReviewBudget, replay
from coolpilot.simulation.camera_comparison import CAMERAS, STREAM_FAULTS, fault_schedule
from coolpilot.models import CameraConfiguration, CameraThresholds, ReplayScenario


class IncrementalStreamChecks(unittest.TestCase):
    def test_seeded_coverage_and_clean_recovery_windows(self):
        faults = dict.fromkeys(CAMERAS, "random")
        first = fault_schedule(faults, 19, 42)
        self.assertEqual(first, fault_schedule(faults, 19, 42))
        self.assertNotEqual(first, fault_schedule(faults, 19, 43))
        seen = set()
        for seed in range(100):
            schedule = fault_schedule(faults, 19, seed)
            for events in schedule.values():
                self.assertEqual(len(events), 1)
                event = events[0]
                seen.add(event["kind"])
                self.assertGreaterEqual(event["start_s"], 2)
                self.assertLessEqual(event["end_s"], 17)
                self.assertGreaterEqual(event["end_s"] - event["start_s"], 1.999)
                self.assertLessEqual(event["end_s"] - event["start_s"], 3.001)
        self.assertEqual(seen, set(STREAM_FAULTS))
        for events in fault_schedule(faults, 5, 42).values():
            self.assertGreaterEqual(events[0]["start_s"], 2)
            self.assertLessEqual(events[0]["end_s"], 3)
            self.assertGreater(events[0]["end_s"], events[0]["start_s"])
        mixed = fault_schedule({"left": "reference", "centre": "freeze", "right": "random"}, 19, 42)
        self.assertEqual(mixed["left"], [])
        self.assertEqual([e["kind"] for e in mixed["centre"]], ["freeze"])

    def test_source_metadata_never_decodes_or_reads_whole_file(self):
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.get.side_effect = {cv2.CAP_PROP_FPS: 10, cv2.CAP_PROP_FRAME_COUNT: 100,
                                   cv2.CAP_PROP_FRAME_WIDTH: 32, cv2.CAP_PROP_FRAME_HEIGHT: 24}.__getitem__
        capture.read.side_effect = AssertionError("Predecode is forbidden")
        path = MagicMock()
        path.open.side_effect = AssertionError("Whole-file hashing is forbidden")
        path.stat.return_value = SimpleNamespace(st_size=12, st_mtime_ns=34)
        with (patch.object(camera_comparison, "video_path", return_value=path),
              patch.object(camera_comparison.cv2, "VideoCapture", return_value=capture)):
            source = camera_comparison._source("left", Event())
        self.assertEqual(source["frames"], 100)
        self.assertNotIn("timestamps_us", source)
        self.assertEqual(source["file_mtime_ns"], 34)

    def test_incremental_pacing_fault_rejection_and_workload_accounting(self):
        # Deterministic clock and I/O, but real replay queue, preprocessing and analyzer.
        clock, stopped, index = [0.0], [False], [-1]
        stop = MagicMock()
        stop.is_set.side_effect = lambda: stopped[0]
        stop.set.side_effect = lambda: stopped.__setitem__(0, True)

        def advance(seconds):
            clock[0] += seconds
            return stopped[0]

        stop.wait.side_effect = advance
        capture = MagicMock()
        capture.isOpened.return_value = True
        read_times = []
        original = np.full((24, 32, 3), 255, dtype=np.uint8)

        def decode():
            index[0] += 1
            read_times.append(clock[0])
            return (True, original) if index[0] < 7 else (False, None)

        capture.read.side_effect = decode
        capture.get.side_effect = lambda prop: {
            cv2.CAP_PROP_FRAME_WIDTH: 32, cv2.CAP_PROP_FRAME_HEIGHT: 24,
            cv2.CAP_PROP_POS_MSEC: index[0] * 100,
        }[prop]

        def thread(*, target, **kwargs):
            worker = MagicMock()
            worker.start.side_effect = target
            return worker

        pool = MagicMock()
        pool.__enter__.return_value = pool

        def submit(fn, *args):
            future = Future()
            future.set_result(fn(*args))
            return future

        pool.submit.side_effect = submit
        events = [
            {"kind": "interruption", "start_s": 0.1, "end_s": 0.2},
            {"kind": "decode_failure", "start_s": 0.2, "end_s": 0.3},
            {"kind": "timestamp_fault", "start_s": 0.3, "end_s": 0.4},
            {"kind": "jitter", "start_s": 0.4, "end_s": 0.5, "max_delay_ms": 50},
            {"kind": "processing_delay", "start_s": 0.5, "end_s": 0.6, "delay_ms": 40},
            {"kind": "resolution", "start_s": 0.6, "end_s": 0.7},
        ]
        displayed = []
        with (patch.object(camera_benchmark, "perf_counter", side_effect=lambda: clock[0]),
              patch.object(camera_benchmark, "Event", return_value=stop),
              patch.object(camera_benchmark, "Thread", side_effect=thread),
              patch.object(camera_benchmark, "ThreadPoolExecutor", return_value=pool),
              patch.object(camera_benchmark.cv2, "VideoCapture", return_value=capture)):
            trace = replay("unused", None, 2, ReplayScenario(clip="unit"),
                           CameraConfiguration(width=320, queue_size=4),
                           SimpleNamespace(thresholds=CameraThresholds(), allow_image_requests=False),
                           ReviewBudget(0), expected_frames=7, fault_events=events, seed=42,
                           transform=lambda image, pts: np.zeros_like(image),
                           observe=lambda snapshot, image: displayed.append((snapshot, image)))
        self.assertEqual(trace["timestamps_us"], list(range(0, 700000, 100000)))
        for frame_number, read_time in enumerate(read_times[1:7], 1):
            self.assertGreaterEqual(read_time + 1e-9, (frame_number - 1) / 10)
        self.assertEqual(trace["interrupted_frames"], 1)
        self.assertEqual([r["reason"] for r in trace["rejections"]], ["decode_failure", "timestamp_fault"])
        self.assertEqual([o["frame"] for o in trace["observations"]], [0, 4, 5, 6])
        stalled = next(o for o in trace["observations"] if o["frame"] == 5)
        self.assertEqual(stalled["injected_delay_ms"], 40)
        self.assertAlmostEqual(stalled["analysis_ms"] - stalled["compute_ms"], 40)
        self.assertEqual(trace["observations"][-1]["analysis_width"], 640)
        self.assertTrue(original.all())
        self.assertTrue(all(o["black_fraction"] == 1 for o in trace["observations"]))
        self.assertTrue(all(not image.any() for _, image in displayed if image is not None))
        self.assertEqual(trace["expected_frames"], sum(trace[k] for k in (
            "processed", "skipped", "dropped", "interrupted_frames", "rejected_frames", "unfinished_frames")))
        jitter = next(i["delay_ms"] for i in trace["injections"] if i["kind"] == "jitter")
        self.assertGreater(jitter, 0)
        self.assertLess(jitter, 50)


if __name__ == "__main__":
    unittest.main()
