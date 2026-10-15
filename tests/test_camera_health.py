import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from coolpilot.camera_benchmark import ReviewBudget, cost_per_camera_hour, replay
from coolpilot.camera_health import gate, score
from coolpilot.models import CameraConfiguration, CameraGoals, CameraThresholds, FaultLimit, ReplayScenario


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
                      "by_fault": {}, "max_age_s": 2, "unknown_fraction": 0,
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


    def test_camera_hour_cost_converts_wall_seconds_to_hours(self):
        self.assertEqual(cost_per_camera_hour(3600, 1800, 2.0, 1.0, 0.5), 7.0)
    def test_replay_returns_transition_and_observation_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "camera.avi"
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 24))
            self.assertTrue(writer.isOpened())
            for level in (90, 100, 110):
                writer.write(np.full((24, 32, 3), level, dtype=np.uint8))
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
                str(video), timestamps, 0.29, ReplayScenario(clip="test"),
                CameraConfiguration(width=320),
                SimpleNamespace(thresholds=CameraThresholds(), allow_image_requests=False, api_timeout_s=5),
                ReviewBudget(0),
            )

        self.assertGreaterEqual(len(result["observations"]), 1)
        self.assertGreaterEqual(len(result["transitions"]), 1)


if __name__ == "__main__":
    unittest.main()
