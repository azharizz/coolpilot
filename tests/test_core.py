"""Camera-only request boundaries and shared evidence lifecycle."""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from coolpilot import api, store
from coolpilot.agent import execute
from coolpilot.api import app
from coolpilot.models import CameraConfiguration, CameraProposal, RunRequest
from coolpilot.runtime import environment


class PersistenceContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patching = patch.object(store, "DATA", Path(self.directory.name))
        self.patching.start()
        store.initialize()
        self.request = RunRequest(camera={
            "dataset_sha256": "a" * 64,
            "goals": {
                "faults": {"blur": {"min_recall": 1, "max_detection_s": 2, "max_recovery_s": 2, "min_events": 1}},
                "max_false_alarms_per_hour": 0, "min_normal_seconds": 30, "max_age_s": 0.5,
                "max_unknown_fraction": 0.1, "max_api_failure_fraction": 0,
            },
        }).model_dump()

    def tearDown(self):
        self.patching.stop()
        self.directory.cleanup()

    def test_camera_contract_rejects_tracking_and_unauthorized_review(self):
        for extra in ({"workload": "tracking"}, {"frames": 300}, {"baseline": {}}, {"goals": {}}):
            with self.assertRaises(ValidationError):
                RunRequest.model_validate({**self.request, **extra})
        with self.assertRaises(ValidationError):
            RunRequest.model_validate({**self.request, "camera": {**self.request["camera"], "baseline": {"mode": "scheduled"}}})
        with self.assertRaises(ValidationError):
            CameraProposal(width=480, rationale="Unsupported resolution")
        with self.assertRaises(ValidationError):
            CameraProposal(config='{"width":320}', rationale="Invalid nested configuration")

    def test_single_active_run_and_restart_preserve_evidence(self):
        run = store.create_run(self.request)
        with self.assertRaises(sqlite3.IntegrityError):
            store.create_run(self.request)
        experiment = store.start_experiment(run, "baseline", CameraConfiguration().model_dump(), "Actual job pending.")
        store.initialize()
        self.assertEqual(store.get_run(run)["status"], "interrupted")
        self.assertEqual(store.experiment(experiment)["status"], "interrupted")
        store.create_run(self.request)

    def test_history_paginates_cameras_and_archives_tracking_without_deletion(self):
        # Simulate a pre-cutover database; legacy evidence remains physically intact.
        with store.database() as db:
            db.execute("INSERT INTO runs(id,created,status,request) VALUES ('legacy',?,'completed',?)",
                       (store.now(), json.dumps({"name": "Mouse-pad optimization"})))
        legacy = store.start_experiment("legacy", "validation", {}, "Historical evidence")
        store.finish_experiment(legacy, {"trace": {}, "environment": {"opencv_build": "legacy"}}, {"passed": True})
        store.update_run("legacy", recommendation=legacy)
        for index in range(17):
            identifier = store.create_run({**self.request, "name": f"Camera {index}"})
            store.update_run(identifier, status="completed")
        running = store.create_run({**self.request, "name": "Current run"})
        first = store.history(1, 8, "Camera", "completed")
        second = store.history(2, 8, "Camera", "completed")
        last = store.history(99, 8, "Camera", "completed")
        self.assertEqual(first["total"], 17)
        self.assertEqual(len(first["items"]), 8)
        self.assertTrue({r["id"] for r in first["items"]}.isdisjoint(r["id"] for r in second["items"]))
        self.assertEqual((last["page"], len(last["items"])), (3, 1))
        self.assertEqual(first["running_id"], running)
        self.assertEqual(store.history(1, 8, "CAMERA 16", "")["total"], 1)
        self.assertEqual(store.history(1, 8, "%_", "")["total"], 0)
        self.assertEqual(store.history(1, 8, "Mouse", "")["total"], 0)
        self.assertEqual(len(store.list_runs()), 18)
        self.assertIsNone(store.get_run("legacy"))
        self.assertIsNone(store.experiment(legacy))
        with self.assertRaisesRegex(ValueError, "Only camera-health"):
            store.promote(legacy)
        with store.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs WHERE id='legacy'").fetchone()[0], 1)
        client = TestClient(app)
        self.assertEqual(client.get("/api/runs/legacy").status_code, 404)
        self.assertEqual(client.get(f"/api/experiments/{legacy}").status_code, 404)
        self.assertEqual(client.get("/api/active?workload=tracking").status_code, 422)
        self.assertEqual(client.get("/api/history?page=0").status_code, 422)
        self.assertEqual(client.get("/api/history?page_size=51").status_code, 422)
        self.assertEqual(client.get("/api/history?status=unknown").status_code, 422)
        self.assertEqual(client.get("/api/history?q=Camera").json()["total"], 17)

    def test_job_failure_releases_run_and_measurement(self):
        run = store.create_run(self.request)

        async def failed_measure(run_id, request, config, kind, rationale):
            store.start_experiment(run_id, kind, config.model_dump(), rationale)
            raise OSError("Unit fixture: process could not be started")

        with patch("coolpilot.agent.measure", failed_measure):
            asyncio.run(execute(run))
        result = store.get_run(run)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["experiments"][0]["status"], "failed")
        store.create_run(self.request)

    def test_camera_promotion_checks_evidence_runtime_and_rollback(self):
        def validated(width):
            # Historical camera requests may contain retired, irrelevant root fields.
            run = store.create_run({**self.request, "frames": 300, "goals": {}, "baseline": {}})
            experiment = store.start_experiment(run, "validation", CameraConfiguration(width=width).model_dump(), "Unit fixture.")
            with self.assertRaises(ValueError):
                store.promote(experiment)
            store.finish_experiment(experiment, {"metrics": {}, "trace": {}, "split": "validation",
                                                "environment": environment()}, {"passed": True})
            store.update_run(run, status="completed", recommendation=experiment)
            return experiment

        first, second = validated(640), validated(320)
        with patch("coolpilot.camera_dataset.checked", return_value={"development_only": True}):
            with self.assertRaisesRegex(ValueError, "Development evidence"):
                store.promote(first)
        with patch("coolpilot.camera_dataset.checked", return_value={"development_only": False}):
            with patch("coolpilot.runtime.environment", return_value={}):
                with self.assertRaisesRegex(ValueError, "Runtime changed"):
                    store.promote(first)
            self.assertEqual(store.promote(first)["experiment_id"], first)
            self.assertEqual(store.promote(second)["experiment_id"], second)
            self.assertEqual(store.rollback()["experiment_id"], first)
            third = validated(960)
            store.promote(third)
            self.assertEqual(store.rollback()["experiment_id"], first)
            with self.assertRaises(ValueError):
                store.rollback()

    def test_http_trust_boundary_and_invalid_input(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(client.post("/api/runs", json={}, headers={"Origin": "https://unrelated.example"}).status_code, 403)
            self.assertEqual(client.get("/api/health", headers={"Host": "unrelated.example"}).status_code, 400)
            self.assertEqual(client.post("/api/runs", json={"budget": 999}).status_code, 422)
            self.assertEqual(client.post("/api/runs", json={**self.request, "workload": "tracking"}).status_code, 422)
            for invalid in ("NaN", "Infinity", "-Infinity"):
                response = client.post("/api/camera-comparison/analyze", content=f'{{"api_timeout_s":{invalid}}}',
                                       headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("input", response.json()["detail"][0])
            self.assertEqual(client.post("/api/experiments/99/apply", json={}).status_code, 409)
            self.assertEqual(client.get("/api/frames/tuning/-1").status_code, 404)
            response = client.get("/api/system")
            self.assertNotIn("NEBIUS_API_KEY", response.text)
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_serverless_switches_are_off_by_default_and_guard_when_set(self):
        with TestClient(app) as client:
            self.assertFalse(client.get("/api/system").json()["readonly"])
            self.assertEqual(client.get("/api/history").status_code, 200)
        with patch.object(api, "BASIC_AUTH", "judge:s3cret"), patch.object(api, "READONLY", True):
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)  # readiness probe stays open
                denied = client.get("/api/history")
                self.assertEqual(denied.status_code, 401)
                self.assertIn("Basic", denied.headers["WWW-Authenticate"])
                self.assertEqual(client.get("/api/history", auth=("judge", "wrong")).status_code, 401)
                ok = client.get("/api/system", auth=("judge", "s3cret"))
                self.assertEqual((ok.status_code, ok.json()["readonly"]), (200, True))
                for path in ("/api/runs", "/api/runs/x/cancel", "/api/experiments/1/apply", "/api/active/rollback"):
                    blocked = client.post(path, json={}, auth=("judge", "s3cret"))
                    self.assertEqual(blocked.status_code, 409, path)
                    self.assertIn("always-on", blocked.json()["detail"])
                # Replay streaming is not a background job, so it must stay reachable (validation still applies).
                self.assertEqual(client.post("/api/camera-comparison/analyze", json={"seed": -1}, auth=("judge", "s3cret")).status_code, 422)

    def test_global_budget_limits_only_expensive_requests_and_only_when_enabled(self):
        spent = []

        def take(bucket):
            spent.append(bucket)
            return spent.count(bucket) <= 2

        body = {"seed": -1}  # fails validation after the budget check, so no replay ever starts
        with TestClient(app) as client:
            for _ in range(5):  # disabled by default: unlimited
                self.assertEqual(client.post("/api/camera-comparison/analyze", json=body).status_code, 422)
        with patch.object(api, "RATE_TABLE", "t"), patch.object(api, "_take", take):
            with TestClient(app) as client:
                codes = [client.post("/api/camera-comparison/analyze", json=body).status_code for _ in range(4)]
                self.assertEqual(codes, [422, 422, 429, 429])
                self.assertIn("busy", client.post("/api/camera-comparison/analyze", json=body).json()["detail"])
                self.assertEqual(client.get("/api/history").status_code, 200)  # cheap endpoints are never metered
                self.assertNotEqual(client.get("/api/camera-comparison/left/video", headers={"Range": "bytes=500-"}).status_code, 429)
                self.assertEqual(spent.count("download"), 0)  # a seek is not a new download
                client.get("/api/camera-comparison/left/video")
                client.get("/api/camera-comparison/left/video", headers={"Range": "bytes=0-99"})
                self.assertEqual(client.get("/api/camera-comparison/left/video").status_code, 429)
                self.assertEqual(client.get("/api/runs/x/export").status_code, 429)

    def test_agent_detector_sent_as_json_string_is_decoded_then_bounded(self):
        from coolpilot.agent import nested_objects
        proposal = CameraProposal.model_validate(nested_objects({"rationale": "r", "detector": '{"obstruction_s": 1.2}'}))
        self.assertEqual(proposal.detector.obstruction_s, 1.2)
        with self.assertRaises(ValidationError):
            CameraProposal.model_validate(nested_objects({"rationale": "r", "detector": '{"obstruction_ratio": 0.2}'}))

    def test_detector_tuning_is_bounded_and_applies_per_experiment_only(self):
        from coolpilot.models import CameraConfiguration, CameraSettings, CameraThresholds
        from coolpilot.simulation.camera_benchmark import merged_settings
        with self.assertRaises(ValidationError):
            CameraConfiguration.model_validate({"detector": {"glare_rise": 0.33}})     # off the finite grid
        settings = CameraSettings.model_validate({**self.request["camera"], "thresholds": {"glare_rise": 0.4}})
        plain = merged_settings(settings, CameraConfiguration())
        self.assertIs(plain, settings)
        tuned = merged_settings(settings, CameraConfiguration.model_validate({"detector": {"glare_rise": 0.25, "hysteresis": 0.7}}))
        self.assertEqual((tuned.thresholds.glare_rise, tuned.thresholds.hysteresis), (0.25, 0.7))
        self.assertEqual(settings.thresholds.glare_rise, 0.4)                          # the frozen run contract is untouched
        self.assertEqual(tuned.goals, settings.goals)                                 # gates never change
        self.assertEqual(tuned.thresholds.dark_ratio, CameraThresholds().dark_ratio)

    def test_cool_detection_needs_linux_arm_and_the_vendor_path(self):
        from coolpilot.runtime import accelerators, distribution
        cv = "/opt/cool/python_3.12/site-packages/cv2/__init__.py"
        self.assertEqual(distribution("Linux", "aarch64", cv), "COOL")
        self.assertEqual(distribution("Linux", "aarch64", "/home/u/venv/site-packages/cv2/__init__.py"), "OpenCV")
        self.assertEqual(distribution("Darwin", "arm64", cv), "OpenCV")
        self.assertEqual(distribution("Linux", "x86_64", cv), "OpenCV")
        self.assertEqual(accelerators("Custom HAL: YES (carotene (ver 0.0.1) KleidiCV (ver 26.03))"), ["KleidiCV", "Carotene"])


if __name__ == "__main__":
    unittest.main()
