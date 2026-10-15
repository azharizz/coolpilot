"""Small contract checks. Geometric fixtures here are test data, never app data."""

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from pydantic import ValidationError

from coolpilot import store
from coolpilot.agent import TOOLS, execute
from coolpilot.api import app
from coolpilot.models import (
    Configuration,
    ExperimentProposal,
    Goals,
    RunRequest,
    pareto_frontier,
    quality_gate,
)
from coolpilot.tracking import evaluate


class MeasurementContract(unittest.TestCase):
    def test_skipped_and_missing_predictions_cannot_improve_quality(self):
        box = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], np.float32)
        truth = np.array([box, box + [2, 0], box + [4, 0]], np.float32)
        held = evaluate([box.tolist()] * 3, truth, 100, 100)
        lost = evaluate([box.tolist(), None, None], truth, 100, 100)
        self.assertAlmostEqual(held["corner_error_px"], 3.0)
        self.assertEqual(held["scored_frames"], 2)
        self.assertEqual(lost["success_rate"], 0)
        self.assertEqual(lost["lost_frames"], 2)
        self.assertAlmostEqual(lost["corner_error_px"], np.hypot(100, 100))

    def test_quality_rejects_faster_but_inaccurate_candidate(self):
        m = {"success_rate": 0.99, "corner_error_px": 4.1, "p95_ms": 1}
        self.assertFalse(quality_gate(m, Goals())["passed"])
        m["corner_error_px"] = 4
        self.assertTrue(quality_gate(m, Goals())["passed"])

    def test_frontier_excludes_failed_and_dominated_experiments(self):
        def row(i, fps, error, p95, valid=True):
            return {
                "id": i,
                "gate": {"passed": valid},
                "metrics": {
                    "throughput_fps": fps,
                    "corner_error_px": error,
                    "p95_ms": p95,
                },
            }

        rows = [
            row(1, 50, 2, 20),
            row(2, 60, 1, 15),
            row(3, 80, 3, 10),
            row(4, 1000, 0, 1, False),
        ]
        self.assertEqual(pareto_frontier(rows), [2, 3])
        self.assertEqual(pareto_frontier(rows + [{"id": 5, "gate": None}]), [2, 3])

    def test_provider_schema_is_flat_and_rejects_stringified_configuration(self):
        schema = TOOLS[0]["function"]["parameters"]
        self.assertNotIn("$defs", schema)
        self.assertIn("width", schema["properties"])
        proposal = ExperimentProposal(width=320, rationale="Measure lower resolution.")
        self.assertEqual(proposal.width, 320)
        with self.assertRaises(ValidationError):
            ExperimentProposal(
                config='{"width":320}', rationale="Invalid provider shape."
            )
        with self.assertRaises(ValidationError):
            Configuration(workers=99)
        with self.assertRaises(ValidationError):
            Goals(max_corner_error_px=float("nan"))


class PersistenceContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patching = patch.object(store, "DATA", Path(self.directory.name))
        self.patching.start()
        store.initialize()

    def tearDown(self):
        self.patching.stop()
        self.directory.cleanup()

    def test_single_active_run_and_restart_preserve_evidence(self):
        run = store.create_run(RunRequest().model_dump())
        with self.assertRaises(sqlite3.IntegrityError):
            store.create_run(RunRequest().model_dump())
        experiment = store.start_experiment(
            run, "baseline", Configuration().model_dump(), "Actual job pending."
        )
        store.initialize()
        self.assertEqual(store.get_run(run)["status"], "interrupted")
        self.assertEqual(store.experiment(experiment)["status"], "interrupted")
        store.create_run(RunRequest().model_dump())

    def test_history_paginates_all_runs_and_keeps_active_run_visible(self):
        for index in range(17):
            identifier = store.create_run(
                RunRequest(name=f"Tracking {index}").model_dump()
            )
            store.update_run(identifier, status="completed")
        running = store.create_run(RunRequest(name="Current run").model_dump())
        first = store.history(1, 8, "Tracking", "completed")
        second = store.history(2, 8, "Tracking", "completed")
        last = store.history(99, 8, "Tracking", "completed")
        self.assertEqual(first["total"], 17)
        self.assertEqual(len(first["items"]), 8)
        self.assertTrue(
            {row["id"] for row in first["items"]}.isdisjoint(
                row["id"] for row in second["items"]
            )
        )
        self.assertEqual((last["page"], len(last["items"])), (3, 1))
        self.assertEqual(first["running_id"], running)
        self.assertEqual(store.history(1, 8, "TRACKING 16", "")["total"], 1)
        self.assertEqual(store.history(1, 8, "%_", "")["total"], 0)
        client = TestClient(app)
        self.assertEqual(client.get("/api/history?page=0").status_code, 422)
        self.assertEqual(client.get("/api/history?page_size=51").status_code, 422)
        self.assertEqual(client.get("/api/history?status=unknown").status_code, 422)
        self.assertEqual(client.get("/api/history?q=Tracking").json()["total"], 17)

    def test_job_failure_releases_run_and_measurement(self):
        run = store.create_run(RunRequest(strategy="baseline").model_dump())

        async def failed_measure(run_id, request, config, kind, rationale):
            store.start_experiment(run_id, kind, config.model_dump(), rationale)
            raise OSError("Unit fixture: process could not be started")

        with patch("coolpilot.agent.measure", failed_measure):
            asyncio.run(execute(run))
        result = store.get_run(run)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["experiments"][0]["status"], "failed")
        store.create_run(RunRequest().model_dump())

    def test_promotion_rejects_unvalidated_and_rollback_restores_prior(self):
        def validated(width):
            run = store.create_run(RunRequest().model_dump())
            experiment = store.start_experiment(
                run,
                "validation",
                Configuration(width=width).model_dump(),
                "Unit fixture.",
            )
            with self.assertRaises(ValueError):
                store.promote(experiment)
            # This fixture tests persistence authorization, not benchmark performance.
            result = {
                "metrics": {},
                "trace": {},
                "environment": {"opencv_build": "unit fixture"},
            }
            store.finish_experiment(experiment, result, {"passed": True})
            store.update_run(run, status="completed", recommendation=experiment)
            return experiment

        first, second = validated(640), validated(320)
        self.assertEqual(store.promote(first)["experiment_id"], first)
        self.assertEqual(store.promote(second)["experiment_id"], second)
        self.assertEqual(store.rollback()["experiment_id"], first)
        third = validated(480)
        store.promote(third)
        self.assertEqual(store.rollback()["experiment_id"], first)
        with self.assertRaises(ValueError):
            store.rollback()

    def test_http_trust_boundary_and_invalid_input(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(
                client.post(
                    "/api/runs",
                    json={},
                    headers={"Origin": "https://unrelated.example"},
                ).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    "/api/health", headers={"Host": "unrelated.example"}
                ).status_code,
                400,
            )
            self.assertEqual(
                client.post("/api/runs", json={"budget": 999}).status_code, 422
            )
            for invalid in ("NaN", "Infinity", "-Infinity"):
                response = client.post("/api/camera-comparison/analyze",
                                       content=f'{{"api_timeout_s":{invalid}}}',
                                       headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("input", response.json()["detail"][0])
            self.assertEqual(
                client.post("/api/experiments/99/apply", json={}).status_code, 409
            )
            self.assertEqual(client.get("/api/frames/tuning/-1").status_code, 404)
            response = client.get("/api/system")
            self.assertNotIn("NEBIUS_API_KEY", response.text)
            self.assertIn(
                "frame-ancestors 'none'", response.headers["Content-Security-Policy"]
            )


if __name__ == "__main__":
    unittest.main()
