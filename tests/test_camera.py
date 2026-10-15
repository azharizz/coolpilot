"""Pure camera contracts only: no server, database, video replay or provider calls."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np
from pydantic import ValidationError

from coolpilot.camera_health import Monitor, analyze, assess_health, score
from coolpilot.decisions import MODEL, QUESTIONS, current_review, parse, review
from coolpilot.simulation.camera_comparison import video_path
from coolpilot.models import CameraThresholds, ReplayInterval, RunRequest
from coolpilot.api import CameraCompareRequest


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

    def test_health_separates_scene_suspicions_and_preserves_freshness(self):
        monitor = Monitor(CameraThresholds())
        for i in range(271):
            # A scene change, not an injected obstruction: preserve the suspicion
            # without asserting that a functioning input/processing path has failed.
            regions = [{"detail": 100.0 if i and j == 0 else 1000.0,
                        "mean": 120.0, "clipped": 0.36 if j == 1 else 0.0}
                       for j in range(16)]
            conditions, _ = monitor.appearance(
                {"regions": regions, "black_fraction": 0.0,
                 "thumbnail": np.full((60, 80), i % 256, dtype=np.uint8)}, i / 14)
            monitor.update(conditions, i / 14, {})
        visual = set(monitor.active)
        self.assertEqual(visual, {"glare", "obstruction"})
        for unavailable, stale, delivery, pipeline, quality in (
            (False, False, set(), "healthy", "suspected"),
            (False, False, {"backlog"}, "degraded", "suspected"),
            (False, True, {"backlog"}, "unknown", "unknown"),
            (True, False, {"interruption"}, "unavailable", "unknown"),
            (True, True, {"interruption"}, "unavailable", "unknown"),
        ):
            state = assess_health(unavailable=unavailable, stale=stale,
                                  delivery_conditions=delivery, visual_conditions=visual)
            self.assertEqual(state["pipeline_status"], pipeline)
            self.assertEqual(state["quality_status"], quality)
            self.assertEqual(set(state["visual_conditions"]), visual)
            self.assertEqual(set(state["delivery_conditions"]), delivery)
        cleared = assess_health(unavailable=False, stale=False,
                                delivery_conditions=set(), visual_conditions=set())
        self.assertEqual(cleared["quality_status"], "no_issue_detected")
        self.assertEqual(cleared["pipeline_status"], "healthy")
        missing = assess_health(unavailable=False, stale=True,
                                delivery_conditions=set(), visual_conditions=set())
        self.assertEqual(missing["quality_status"], "unknown")
        self.assertEqual(missing["pipeline_status"], "unknown")

    def test_reference_decay_uses_source_time_not_sample_count(self):
        references = []
        for rate in (5, 14, 30):
            monitor = Monitor(CameraThresholds(reference_decay_s=10))
            for i in range(10 * rate + 1):
                measured = {"regions": [{"detail": 1000.0 if i == 0 else 1.0,
                                         "mean": 120.0, "clipped": 0.0} for _ in range(16)],
                            "black_fraction": 0.0, "thumbnail": np.zeros((60, 80), np.uint8)}
                monitor.appearance(measured, i / rate)
            references.append(monitor.reference_detail.copy())
            for invalid in (10, 9, float("nan"), float("inf"), -1):
                with self.assertRaises(ValueError):
                    monitor.appearance(measured, invalid)
            np.testing.assert_allclose(monitor.reference_detail, references[-1])
        for reference in references:
            np.testing.assert_allclose(reference, np.full(16, 1000 / np.e), rtol=1e-12)
        # Decay must precede comparison, including after an observation gap.
        for region in measured["regions"]:
            region["detail"] = 1000
        measured["regions"][0]["detail"] = 50
        conditions, _ = monitor.appearance(measured, 20)
        self.assertNotIn("obstruction", conditions)

    def test_advice_expires_from_source_time_and_preserves_history(self):
        original = {"status": "ok", "pts_s": 2.0, "received_s": 2.25,
                    "probabilities": {"blur": 0.9}, "cost": 0.01}
        self.assertEqual(current_review(original, 2.49, 0.5)["probabilities"], {"blur": 0.9})
        expired = current_review(original, 2.5, 0.5)
        self.assertEqual(expired["status"], "expired")
        self.assertNotIn("probabilities", expired)
        self.assertEqual(expired["cost"], 0.01)
        self.assertEqual(original["probabilities"], {"blur": 0.9})
        self.assertEqual(original["status"], "ok")
        delayed = {**original, "received_s": 3.0}
        self.assertEqual(current_review(delayed, 3.0, 0.5)["status"], "expired")
        for invalid in (None, True, float("nan"), -1, 4):
            unavailable = current_review({**original, "pts_s": invalid}, 3, 0.5)
            self.assertEqual(unavailable["status"], "unavailable")
            self.assertNotIn("probabilities", unavailable)
        self.assertEqual(current_review({**original, "status": "unavailable"}, 2.3, 0.5)["status"], "unavailable")
        self.assertIsNone(current_review(None, 2.3, 0.5))

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
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        payload = {"answers": {key: {"type": "noul", "noul": 0.2} for key in QUESTIONS}}
        for statuses in ((404, 200), (400,), (404, 404)):
            calls = []

            def respond(request):
                status = statuses[len(calls)]
                calls.append(request)
                return httpx.Response(status, json=payload if status == 200 else {"error": {"message": "rejected"}})

            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with (patch.dict("os.environ", {"AGENT_PROVIDER_API_KEY": "test", "AGENT_PROVIDER_MODEL": MODEL}),
                  patch("coolpilot.decisions.asyncio.sleep", new_callable=AsyncMock),
                  patch("coolpilot.decisions.httpx.AsyncClient", return_value=client)):
                result = review(frame, timeout_s=5)
            self.assertEqual(len(calls), len(statuses))
            if statuses[-1] == 200:
                self.assertEqual(result["probabilities"]["blur"], 0.2)
            else:
                self.assertEqual(result["status"], "unavailable")
                self.assertIn(f"HTTP {statuses[-1]}: rejected", result["error"])

    def test_total_deadline_cancels_headers_body_and_retry(self):
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        for phase in ("headers", "body", "retry"):
            cancelled = []
            calls = []

            class StalledBody(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield b'{"answers":'
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.append("body")

            async def respond(request):
                calls.append(request)
                if phase == "headers":
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.append("headers")
                if phase == "retry":
                    return httpx.Response(404)
                return httpx.Response(200, stream=StalledBody())

            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with (patch.dict("os.environ", {"AGENT_PROVIDER_API_KEY": "test", "AGENT_PROVIDER_MODEL": MODEL}),
                  patch("coolpilot.decisions.httpx.AsyncClient", return_value=client)):
                result = review(frame, timeout_s=0.05)
            self.assertEqual(result["status"], "unavailable")
            self.assertNotIn("probabilities", result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(cancelled, [] if phase == "retry" else [phase])
            self.assertTrue(client.is_closed)

    def test_malformed_provider_answers_preserve_unavailable_state(self):
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        for raw in ({"answers": dict.fromkeys(QUESTIONS)},
                    {"answers": {}, "usage": None}):
            with (patch("coolpilot.decisions.configured", return_value=True),
                  patch("coolpilot.decisions._post", return_value=(raw, None))):
                self.assertEqual(review(frame, 1)["status"], "unavailable")

    def test_workload_and_time_boundaries(self):
        with self.assertRaises(ValidationError):
            RunRequest(workload="camera_health")
        with self.assertRaises(ValidationError):
            ReplayInterval(start_s=2, end_s=2)

    def test_comparison_video_source_is_allowlisted(self):
        for camera in ("../stereo_left.mp4", "left/../../README.md", "unknown"):
            with self.assertRaises(ValueError):
                video_path(camera)

    def test_live_review_requires_consent_and_bounded_inputs(self):
        for invalid in (
            {"mode": "scheduled"}, {"mode": "hybrid"},
            {"faults": {"left": "blur", "centre": "blackout"}},
            {"faults": {"left": "blur", "centre": "blackout", "right": "unknown"}},
            {"api_timeout_s": float("nan")}, {"review_limit": 11}, {"review_interval_s": 3},
        ):
            with self.assertRaises(ValidationError):
                CameraCompareRequest(**invalid)
        request = CameraCompareRequest(mode="scheduled", allow_image_requests=True, review_limit=1)
        self.assertEqual(request.mode, "scheduled")


if __name__ == "__main__":
    unittest.main()
