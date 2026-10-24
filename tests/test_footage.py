import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from coolpilot import api, footage
from coolpilot.api import app


def clip(path: Path, frames: int = 60, black_from: int = 30):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 15, (320, 240))
    rng = np.random.default_rng(1)
    for i in range(frames):
        writer.write(np.zeros((240, 320, 3), np.uint8) if i >= black_from else rng.integers(0, 255, (240, 320, 3), dtype=np.uint8))
    writer.release()


class FootageChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.video = self.root / "clip.mp4"
        clip(self.video)

    def tearDown(self):
        self.directory.cleanup()

    def test_screen_reports_blackout_segment(self):
        report = footage.screen(str(self.video))
        self.assertEqual([s["type"] for s in report["segments"]], ["blackout"])
        self.assertGreater(report["segments"][0]["start_s"], 1.9)

    def test_local_upload_is_analysed_once_then_deleted(self):
        with patch.object(api, "DATA_DIR", self.root), patch.object(api, "UPLOAD_BUCKET", ""):
            client = TestClient(app)
            slot = client.post("/api/footage").json()
            self.assertEqual(slot["upload"]["method"], "PUT")
            self.assertEqual(client.put(slot["upload"]["url"], content=self.video.read_bytes()).status_code, 204)
            lines = client.post(f"/api/footage/{slot['id']}/analyze").text.strip().splitlines()
            report = json.loads(lines[-1])
            self.assertEqual(report["type"], "report")
            self.assertEqual([s["type"] for s in report["segments"]], ["blackout"])
            self.assertFalse((self.root / "uploads" / f"{slot['id']}.video").exists())
            self.assertEqual(client.post(f"/api/footage/{slot['id']}/analyze").status_code, 404)

    def test_bad_ids_and_oversized_uploads_are_refused(self):
        with patch.object(api, "DATA_DIR", self.root), patch.object(api, "UPLOAD_BUCKET", ""), patch.object(footage, "MAX_BYTES", 10):
            client = TestClient(app)
            self.assertEqual(client.post("/api/footage/NOT-A-VALID-ID/analyze").status_code, 404)
            slot = client.post("/api/footage").json()
            self.assertEqual(client.put(slot["upload"]["url"], content=b"x" * 100).status_code, 413)
            self.assertFalse((self.root / "uploads" / f"{slot['id']}.video").exists())


if __name__ == "__main__":
    unittest.main()
