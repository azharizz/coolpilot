import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from coolpilot.simulation import camera_benchmark
from coolpilot.simulation.camera_benchmark import ReviewBudget, cost_per_camera_hour, replay
from coolpilot.camera_health import analyze, gate, score
from coolpilot.models import CameraConfiguration, CameraGoals, CameraThresholds, FaultLimit, ReplayScenario


class AnalyzerContract(unittest.TestCase):
    def test_opencv_tile_statistics_match_their_numpy_definitions(self):
        # Guards any OpenCV build swap (e.g. COOL): measurements must not drift.
        rng = np.random.default_rng(7)
        frame = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
        frame[:120, :160] = 255
        frame[-120:, -160:] = 0
        measured = analyze(frame, 640)
        gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (320, 240), interpolation=cv2.INTER_AREA)
        laplacian = cv2.Laplacian(gray, cv2.CV_32F).astype(np.float64)
        for i, region in enumerate(measured["regions"]):
            rows, cols = slice(i // 4 * 60, i // 4 * 60 + 60), slice(i % 4 * 80, i % 4 * 80 + 80)
            self.assertAlmostEqual(region["mean"], gray[rows, cols].mean(), places=9)
            self.assertAlmostEqual(region["detail"], laplacian[rows, cols].var(), delta=1e-6 * max(1, region["detail"]))
            self.assertEqual(region["clipped"], np.mean(gray[rows, cols] >= 250))
        self.assertEqual(measured["regions"][0]["clipped"], 1)
        self.assertEqual(measured["black_fraction"], np.mean(gray < 8))


class CameraScoringContract(unittest.TestCase):
    def test_unknown_visual_evidence_is_missed_but_not_a_false_alarm(self):
        events = [{"type": "blur", "start_s": 2.0, "end_s": 4.0,
                   "severity": "strong", "provenance": "fixture"}]
        episodes = [{"type": "blur", "start_s": 2.6, "end_s": 4.3},
                    {"type": "interruption", "start_s": 2.6, "end_s": 3.0}]
        result = score(events, episodes, 10.0,
                       [{"start_s": 2.5, "end_s": 2.8, "reason": "stale"}])
        self.assertFalse(result["matches"][0]["detected"])
        self.assertTrue(result["matches"][0]["unknown_evidence"])
        self.assertEqual([a["type"] for a in result["false_alarms"]], ["interruption"])
        self.assertAlmostEqual(result["normal_seconds"], 8.0)

    def test_source_age_and_required_remote_coverage_are_gates(self):
        goals = CameraGoals(
            faults={"blur": FaultLimit(min_recall=0.9, max_detection_s=1,
                                        max_recovery_s=1, min_events=1)},
            max_false_alarms_per_hour=1, min_normal_seconds=1, max_age_s=1,
            max_unknown_fraction=0.2, max_api_failure_fraction=0.1,
        )
        evaluation = {"clip": "c", "repetition": 0, "stream": 0,
                      "by_fault": {}, "max_age_s": 2, "unknown_fraction": 0.3,
                      "api_failure_fraction": 0, "review_required": 10,
                      "review_coverage": 0.8, "unfinished_frames": 0}
        metrics = {"evaluations": [evaluation],
                   "repetition_evidence": [{"repetition": 0, "event_counts": {"blur": 1},
                                            "normal_seconds": 10, "false_alarms_per_hour": 0}],
                   "cost_per_camera_hour": None}
        result = gate(metrics, goals)
        checks = {check["metric"]: check for check in result["checks"]}
        self.assertFalse(checks["c r1 s1: maximum source-schedule-to-result age seconds"]["passed"])
        self.assertFalse(checks["c r1 s1: image-review coverage"]["passed"])
        self.assertFalse(checks["c r1 s1: unknown evidence fraction"]["passed"])


    def test_camera_hour_cost_converts_wall_seconds_to_hours(self):
        self.assertEqual(cost_per_camera_hour(3600, 1800, 2.0, 1.0, 0.5), 7.0)
    def test_scheduled_review_never_suppresses_local_blackout(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "camera.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
            self.assertTrue(writer.isOpened())
            for _ in range(12):
                writer.write(np.zeros((24, 32, 3), dtype=np.uint8))
            writer.release()

            capture = cv2.VideoCapture(str(video))
            timestamps = []
            while True:
                ok, _ = capture.read()
                if not ok:
                    break
                timestamps.append(round(capture.get(cv2.CAP_PROP_POS_MSEC) * 1000))
            capture.release()
            result = replay(
                str(video), timestamps, 1.2, ReplayScenario(clip="test"),
                CameraConfiguration(width=320, mode="scheduled"),
                SimpleNamespace(thresholds=CameraThresholds(), allow_image_requests=False, api_timeout_s=5),
                ReviewBudget(0),
            )
            delayed = replay(
                str(video), timestamps, 1.2,
                ReplayScenario(clip="test", processing_delay_ms=700,
                               processing_delay_interval={"start_s": 0, "end_s": 1.2}),
                CameraConfiguration(width=320),
                SimpleNamespace(thresholds=CameraThresholds(), allow_image_requests=False, api_timeout_s=5),
                ReviewBudget(0),
            )

        self.assertTrue(any(e["type"] == "blackout" for e in result["episodes"]))
        self.assertEqual(result["transitions"][-1]["pipeline_status"], "healthy")
        self.assertEqual(result["transitions"][-1]["quality_status"], "suspected")
        self.assertIn("blackout", result["transitions"][-1]["visual_conditions"])
        self.assertEqual(result["reviews"], [])
        self.assertEqual(delayed["unknown_fraction"], 1)
        self.assertFalse(any(s["pipeline_status"] == "healthy" for s in delayed["transitions"]))
        self.assertNotIn("blackout", {e["type"] for e in delayed["episodes"]})
        self.assertGreaterEqual(delayed["max_age_s"], 0.5)

    def test_review_slots_and_unfinished_source_frames_with_fake_io(self):
        # No decoding, threads, network, or wall-clock replay: advance a deterministic clock.
        for deliver in (True, False):
            clock = [0.0]
            stopped = [False]
            stop = MagicMock()
            stop.is_set.side_effect = lambda: stopped[0]
            stop.set.side_effect = lambda: stopped.__setitem__(0, True)

            def advance(seconds):
                clock[0] += seconds
                return stopped[0]

            stop.wait.side_effect = advance
            frame = np.full((24, 32, 3), 255, dtype=np.uint8)
            capture = MagicMock()
            capture.isOpened.return_value = True
            capture.get.side_effect = lambda prop: {
                cv2.CAP_PROP_FRAME_WIDTH: 32, cv2.CAP_PROP_FRAME_HEIGHT: 24,
                cv2.CAP_PROP_POS_MSEC: 0,
            }[prop]
            capture.read.side_effect = [(True, frame), (False, None)]
            worker = MagicMock()

            def thread(*, target, **kwargs):
                worker.start.side_effect = target if deliver else None
                return worker

            pending_review = MagicMock()
            pending_review.done.return_value = False
            pending_review.result.return_value = {"status": "ok", "cost": 0.01, "probabilities": {"blackout": 1}}
            pool = MagicMock()
            pool.__enter__.return_value = pool

            def submit(fn, *args):
                if fn is camera_benchmark.review:
                    return pending_review
                future = Future()
                future.set_result(fn(*args))
                return future

            pool.submit.side_effect = submit
            timestamps = [0] if deliver else [0, 100000, 200000]
            scenario = ReplayScenario(clip="unit", interruptions=[] if deliver else [
                {"start_s": 0.1, "end_s": 0.2},
            ])
            observed = []

            def observe(snapshot, image):
                if image is not None:
                    observed.append((snapshot, image))

            with (patch.object(camera_benchmark, "perf_counter", side_effect=lambda: clock[0]),
                  patch.object(camera_benchmark, "Event", return_value=stop),
                  patch.object(camera_benchmark, "Thread", side_effect=thread),
                  patch.object(camera_benchmark, "ThreadPoolExecutor", return_value=pool),
                  patch.object(camera_benchmark.cv2, "VideoCapture", return_value=capture)):
                result = replay("unused", timestamps, 4.5, scenario,
                                CameraConfiguration(width=320, mode="scheduled", review_interval_s=1),
                                SimpleNamespace(thresholds=CameraThresholds(feed_timeout_s=10, backlog_s=10),
                                                allow_image_requests=True, api_timeout_s=10),
                                ReviewBudget(1), transform=lambda image, pts: np.zeros_like(image),
                                observe=observe)
            self.assertEqual(result["review_required"], 5)
            self.assertEqual(len(result["reviews"]), 5)
            statuses = [r["status"] for r in result["reviews"]]
            if deliver:
                self.assertEqual(statuses.count("busy"), 3)
                self.assertEqual(statuses.count("no_evidence"), 1)
                self.assertEqual(statuses.count("unavailable"), 1)
                late = next(r for r in result["reviews"] if r["attempted"])
                self.assertTrue(late["late"])
                self.assertNotIn("probabilities", late)
                self.assertEqual(late["cost"], 0.01)
                self.assertTrue(observed)
                snapshot, displayed = observed[-1]
                self.assertEqual(snapshot["evidence"]["black_fraction"], 1)
                self.assertFalse(displayed.any())
                self.assertTrue(frame.all())  # Source remains untouched.
                self.assertIn("blackout", snapshot["evidence"]["local_conditions"])
                self.assertEqual(snapshot["review_pending"]["pts_s"], snapshot["evidence"]["pts_s"])
            else:
                self.assertEqual(statuses, ["no_evidence"] * 5)
                self.assertFalse(any(r["attempted"] for r in result["reviews"]))
            self.assertEqual(result["unfinished_frames"], 0 if deliver else 2)
            self.assertEqual(result["expected_frames"],
                             sum(result[k] for k in ("processed", "skipped", "dropped",
                                                    "interrupted_frames", "unfinished_frames")))

    def test_cancelled_replay_leaves_unseen_source_unknown(self):
        cancel = camera_benchmark.Event()
        cancel.set()
        with patch.object(camera_benchmark, "Thread"):
            result = replay("unused", [0.0, 0.1, 0.2], 1.0, ReplayScenario(clip="unit"),
                            CameraConfiguration(),
                            SimpleNamespace(thresholds=CameraThresholds(), allow_image_requests=False,
                                            api_timeout_s=1),
                            ReviewBudget(0), cancel=cancel)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["unfinished_frames"], 3)
        self.assertEqual(result["unknown_fraction"], 1)
        self.assertEqual(result["observations"], [])


if __name__ == "__main__":
    unittest.main()
