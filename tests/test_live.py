import json
import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from coolpilot import live_source
from coolpilot.api import app


class LiveSourceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.video = str(Path(self.directory.name) / "live.mp4")
        writer = cv2.VideoWriter(self.video, cv2.VideoWriter_fourcc(*"mp4v"), 20, (320, 240))
        rng = np.random.default_rng(0)
        for _ in range(40):
            writer.write(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8))
        writer.release()

    def tearDown(self):
        self.directory.cleanup()

    def test_file_source_streams_and_stops(self):
        messages = []
        result = live_source.monitor(self.video, 1.0, messages.append, Event(), emit_every_s=0.1)
        self.assertGreater(result["frames"], 0)
        self.assertFalse(result["scored"])
        self.assertTrue(messages and messages[-1]["pipeline_status"] in ("healthy", "unavailable"))

    def test_missing_source_gives_up(self):
        result = live_source.monitor(str(Path(self.directory.name) / "absent.mp4"), 30, lambda _: None, Event(), max_reconnects=1)
        self.assertEqual(result["frames"], 0)
        self.assertLess(result["seconds"], 5)

    def test_api_only_serves_configured_names(self):
        with patch.dict(os.environ, {"COOLPILOT_LIVE_SOURCES": f"test={self.video}"}):
            client = TestClient(app)
            self.assertEqual(client.get("/api/live").json(), {"sources": ["test"]})
            self.assertEqual(client.post("/api/live/analyze", json={"source": "other"}).status_code, 404)
            lines = client.post("/api/live/analyze", json={"source": "test", "seconds": 0.5}).text.strip().splitlines()
            self.assertEqual(json.loads(lines[-1])["type"], "result")


if __name__ == "__main__":
    unittest.main()
