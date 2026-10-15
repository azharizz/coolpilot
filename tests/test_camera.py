"""Pure camera contracts only: no server, database, video replay or provider calls."""
import json
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from pydantic import ValidationError

from coolpilot.camera_health import Monitor, analyze, score
from coolpilot.decisions import MODEL, QUESTIONS, parse, review
from coolpilot.camera_comparison import video_path
from coolpilot.models import CameraThresholds, ReplayInterval, RunRequest


class CameraChecks(unittest.TestCase):
    def test_persistence_recovery_and_duplicate_scoring(self):
        monitor = Monitor(CameraThresholds(persistence_s=0.2, recovery_s=0.2))
        monitor.update({"blackout"}, 1.0, {})
        monitor.update(set(), 1.1, {})
        self.assertEqual(monitor.episodes, [])
        monitor.update({"blackout"}, 2.0, {})
        monitor.update({"blackout"}, 2.3, {})
        monitor.update(set(), 4.0, {})
        monitor.update(set(), 4.3, {})
        self.assertEqual(monitor.active, {})
        result = score([{"type": "blackout", "start_s": 2, "end_s": 4}],
                       monitor.episodes + [{"type": "blackout", "start_s": 3, "end_s": 4}], 6)
        self.assertAlmostEqual(result["matches"][0]["detection_s"], 0.3)
        self.assertAlmostEqual(result["matches"][0]["recovery_s"], 0.3)
        self.assertEqual(len(result["false_alarms"]), 1)
        self.assertEqual(result["normal_seconds"], 4)

    def test_early_alarm_does_not_hide_missed_fault(self):
        result = score([{"type": "freeze", "start_s": 2, "end_s": 4}],
                       [{"type": "freeze", "start_s": 1, "end_s": None}], 5)
        self.assertFalse(result["matches"][0]["detected"])
        self.assertEqual(len(result["false_alarms"]), 1)

    def test_black_content_and_temporal_freeze_are_distinct(self):
        monitor = Monitor(CameraThresholds(freeze_s=1))
        black = analyze(np.zeros((240, 320, 3), dtype=np.uint8), 320)
        first, _ = monitor.appearance(black, 0)
        self.assertIn("blackout", first)
        self.assertNotIn("freeze", first)
        monitor.appearance(black, 0.1)
        later, _ = monitor.appearance(black, 1.2)
        self.assertIn("freeze", later)

    def test_refusal_and_invalid_probabilities_fail_closed(self):
        payload = {"answers": {k: {"type": "noul", "noul": 0.1} for k in QUESTIONS}}
        self.assertIsNone(parse(payload)["cost"])
        for invalid in (True, float("nan"), -0.1, 1.1, None):
            payload["answers"]["blur"]["noul"] = invalid
            with self.assertRaises(ValueError):
                parse(payload)
        payload["answers"]["blur"] = {"type": "refusal"}
        with self.assertRaises(ValueError):
            parse(payload)


    def test_review_retries_one_404_and_returns_final_provider_error(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        body = json.dumps({
            "answers": {key: {"type": "noul", "noul": 0.2} for key in QUESTIONS},
            "usage": {"input_tokens": 1, "output_tokens": 0},
        }).encode()
        responses = [MagicMock(), MagicMock()]
        responses[0].status_code = 404
        responses[1].status_code = 200
        responses[1].iter_bytes.return_value = [body]
        clients = []
        for response in responses:
            client = MagicMock()
            client.__enter__.return_value = client
            client.__exit__.return_value = False
            stream = MagicMock()
            stream.__enter__.return_value = response
            stream.__exit__.return_value = False
            client.stream.return_value = stream
            clients.append(client)

        with (patch.dict("os.environ", {"AGENT_PROVIDER_API_KEY": "test", "AGENT_PROVIDER_MODEL": MODEL}),
              patch("coolpilot.decisions.sleep") as delay,
              patch("coolpilot.decisions.httpx.Client", side_effect=clients) as client_factory):
            result = review(frame, timeout_s=5)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["probabilities"]["blur"], 0.2)
        self.assertEqual(client_factory.call_count, 2)
        delay.assert_called_once_with(0.25)

        response = MagicMock()
        response.status_code = 400
        response.iter_bytes.return_value = [b'{"error":{"message":"invalid request"}}']
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        stream = MagicMock()
        stream.__enter__.return_value = response
        stream.__exit__.return_value = False
        client.stream.return_value = stream
        with (patch.dict("os.environ", {"AGENT_PROVIDER_API_KEY": "test", "AGENT_PROVIDER_MODEL": MODEL}),
              patch("coolpilot.decisions.sleep") as delay,
              patch("coolpilot.decisions.httpx.Client", return_value=client) as client_factory):
            result = review(frame, timeout_s=5)
        self.assertIn("Image provider HTTP 400: invalid request", result["error"])
        client_factory.assert_called_once()
        delay.assert_not_called()

    def test_workload_and_time_boundaries(self):
        with self.assertRaises(ValidationError):
            RunRequest(workload="camera_health")
        with self.assertRaises(ValidationError):
            ReplayInterval(start_s=2, end_s=2)

    def test_comparison_video_source_is_allowlisted(self):
        for camera in ("../stereo_left.mp4", "left/../../README.md", "unknown"):
            with self.assertRaises(ValueError):
                video_path(camera)


if __name__ == "__main__":
    unittest.main()
