import asyncio
import json
import os
import time
import unittest
from unittest.mock import patch

import numpy as np

from coolpilot import objects, verify, verify_agent
from coolpilot.camera_health import Monitor
from coolpilot.models import CameraThresholds

BOXES = [[x / 4, y / 4, 0.25, 0.25] for y in range(4) for x in range(4)]


def frame(top_right_sky=True):
    rng = np.random.default_rng(0)
    image = rng.integers(40, 160, (480, 640, 3), dtype=np.uint8)
    if top_right_sky:
        image[0:120, 160:320] = 235   # tile 1: bright, unsaturated, featureless
    else:
        image[0:120, 160:320] = (58, 70, 82)   # tile 1: dark tinted smudge
    return image


class VerifyChecks(unittest.TestCase):
    def test_open_sky_is_dismissed_but_a_dark_smudge_is_not(self):
        reference = [1000.0] * 16
        sky = verify.gather([frame(), frame()], BOXES, [1], reference)
        self.assertEqual(sky["texture"]["open_sky_tiles"], [1])
        self.assertEqual(verify.rule_verdict(sky, [1])["verdict"], "dismiss")
        smudge = verify.gather([frame(False), frame(False)], BOXES, [1], reference)
        self.assertEqual(smudge["texture"]["unsuitable_tiles"], [])
        self.assertEqual(verify.rule_verdict(smudge, [1])["verdict"], "confirm")

    def test_never_detailed_tile_is_unsuitable(self):
        reference = [1000.0] * 16
        reference[5] = 50.0
        evidence = verify.texture(frame(False), BOXES, reference, [5])
        self.assertEqual(evidence["unsuitable_tiles"], [5])

    def test_road_user_coverage(self):
        boxes = [{"label": "truck", "score": 0.9, "box": [0.0, 0.0, 0.25, 0.25]}]
        self.assertAlmostEqual(objects.coverage(boxes, BOXES[0]), 1.0)
        self.assertEqual(objects.coverage(boxes, BOXES[15]), 0.0)

    @unittest.skipUnless(objects.available(), "detector model not installed")
    def test_shared_detector_is_safe_across_replay_threads(self):
        from concurrent.futures import ThreadPoolExecutor
        images = [frame(), frame(False)] * 4
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda image: objects.detect(image)["objects"], images))
        self.assertTrue(all(r == results[i % 2] for i, r in enumerate(results)))

    def test_replay_verifier_keeps_alarm_when_agent_is_unavailable(self):
        monitor = Monitor(CameraThresholds())
        monitor.recent_detail = np.full(16, 1000.0)
        monitor.active["obstruction"] = {"type": "obstruction", "start_s": 1.0, "end_s": None}
        checker = verify.ReplayVerifier("agent")
        checker.frame(1.0, frame())
        regions = [{"box": b, "suspected_obstruction": i == 1} for i, b in enumerate(BOXES)]
        with patch.dict(os.environ, {"NEBIUS_MODEL": "", "NEBIUS_API_KEY": "", "NEBIUS_BASE_URL": ""}):
            checker.step(monitor, regions, 1.0)
            for _ in range(200):
                checker.step(monitor, regions, 1.5)
                if checker.log:
                    break
                time.sleep(0.01)
        checker.close()
        self.assertEqual(checker.log[0]["verdict"], "confirm")
        self.assertIn("obstruction", monitor.active)

    def test_agent_cannot_decide_before_measuring(self):
        replies = iter([
            {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "function": {"name": "decide", "arguments": json.dumps({"verdict": "dismiss", "reason": "sky"})}}]},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "b", "function": {"name": "inspect_texture", "arguments": "{}"}}]},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "function": {"name": "decide", "arguments": json.dumps({"verdict": "dismiss", "reason": "x" * 900})}}]},
        ])

        async def fake(messages, tools, temperature=None):
            return next(replies), {}

        with patch.object(verify_agent, "provider", fake):
            result = asyncio.run(verify_agent.investigate([frame()], BOXES, [1], [1000.0] * 16))
        self.assertEqual(result["tool_calls"][0], "decide (refused: no measurement yet)")
        self.assertEqual(result["verdict"], "dismiss")
        self.assertEqual(len(result["reason"]), 600)


if __name__ == "__main__":
    unittest.main()
