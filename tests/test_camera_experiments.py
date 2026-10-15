"""Deterministic candidate checks; no server, video replay or paid API."""
import unittest

import cv2
import numpy as np

from coolpilot.camera_health import analyze
from experiments.camera_health import Candidate
from experiments.feature_classifier import fit_evaluate, features
from experiments.opencv_profile import compare


class ExperimentChecks(unittest.TestCase):
    def test_sparse_flow_static_motion_and_missing_texture(self):
        rng = np.random.default_rng(42)
        image = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
        candidate = Candidate("flow")
        candidate.measure(image, analyze(image, 320), 0)
        still = candidate.measure(image, analyze(image, 320), 0.1)
        self.assertTrue(still["repeated_imagery"])
        self.assertFalse(still["repeat_after_motion"])
        moved = cv2.warpAffine(image, np.float32([[1, 0, 3], [0, 1, 0]]), (320, 240))
        flow = candidate.measure(moved, analyze(moved, 320), 0.2)
        self.assertEqual(flow["motion_evidence"], "moving")
        self.assertAlmostEqual(flow["motion_px_s"], 30, delta=2)
        repeated = candidate.measure(moved, analyze(moved, 320), 0.3)
        self.assertTrue(repeated["repeat_after_motion"])
        static = Candidate("flow")
        black = np.zeros_like(image)
        static.measure(black, analyze(black, 320), 0)
        self.assertEqual(static.measure(black, analyze(black, 320), 1)["motion_evidence"], "unknown")

    def test_fixed_coordinate_loss_requires_continuous_scene_motion(self):
        rng = np.random.default_rng(19)
        source = rng.integers(0, 256, (240, 320, 3), dtype=np.uint8)
        candidate = Candidate("persistence", persistence_s=0.15)
        for i in range(4):
            image = cv2.warpAffine(source, np.float32([[1, 0, i * 3], [0, 1, 0]]), (320, 240))
            measured = analyze(image, 320)
            measured["regions"][0]["suspected_obstruction"] = True
            result = candidate.measure(image, measured, i * 0.1)
        self.assertEqual(result["persistent_loss_tiles"], [0])
        self.assertEqual(candidate.measure(image, measured, 0.4)["persistent_loss_tiles"], [])

    def test_ema_sampling_invariance_and_explicit_spatial_weights(self):
        image = np.zeros((24, 32, 3), dtype=np.uint8)
        values = []
        for rate in (5, 20):
            candidate = Candidate("ema", tau_s=1)
            for i in range(rate + 1):
                measured = {"regions": [{"detail": 100 if i == 0 else 0, "clipped": 0} for _ in range(16)]}
                result = candidate.measure(image, measured, i / rate)
            values.append(result["smoothed_severity"])
        np.testing.assert_allclose(values, [1 - np.exp(-1)] * 2)
        measured["regions"][0]["detail"] = 100
        result = Candidate("spatial", weights=[1] + [0] * 15).measure(image, measured, 0)
        self.assertEqual(result["weighted_severity"], 0)
        self.assertEqual(result["uniform_severity"], 15 / 16)
        for weights in (None, [0] * 16, [float("nan")] * 16, [-1] + [1] * 15):
            with self.assertRaises(ValueError):
                Candidate("spatial", weights=weights)
        with self.assertRaises(ValueError):
            Candidate("brisque")

    def test_classifier_held_out_separation_and_train_only_scaling(self):
        x = np.zeros((6, 49), np.float32)
        x[:, 0] = [-2, -1, 1, 2, -100, 100]
        labels = ["normal", "normal", "blur", "blur", "normal", "blur"]
        sessions = ["a"] * 4 + ["b"] * 2
        splits = ["train"] * 4 + ["test"] * 2
        model, mean, scale, report = fit_evaluate(x, labels, sessions, splits)
        self.assertEqual(report["test_predictions"], ["normal", "blur"])
        self.assertEqual(report["accuracy"], 1)
        self.assertEqual(report["confusion_true_rows_predicted_columns"][0][0], 1)
        self.assertAlmostEqual(float(scale[0]), np.std([-2, -1, 1, 2]), places=6)
        self.assertEqual(float(mean[0]), 0)
        with self.assertRaises(ValueError):
            fit_evaluate(x, labels, ["a"] * 6, splits)
        with self.assertRaises(ValueError):
            fit_evaluate(x, labels[:-1] + ["glare"], sessions, splits)
        black = features(analyze(np.zeros((24, 32, 3), np.uint8), 320))
        white = features(analyze(np.full((24, 32, 3), 255, np.uint8), 320))
        self.assertEqual(float(black[-1]), 1)
        self.assertEqual(float(white[-1]), 0)
        self.assertEqual(float(white[2]), 1)

    def test_build_comparison_flags_changed_alarms_and_refuses_unlike_inputs(self):
        def profile(conditions, sha="x", cpu=1.0):
            frame = {"pts_s": 0, "conditions": conditions, "regions": [[1, 2, 0]] * 16, "black_fraction": 0}
            video = {"sha256": sha, "frames": 1, "cpu_s": dict.fromkeys(("decode", "opencv_analysis", "python_alarms", "flow_candidate"), cpu),
                     "other_cpu_s": 0, "total_cpu_s": 4 * cpu, "episodes": [], "detections": [frame]}
            return {"environment": {}, "settings": {"width": 640, "threads": 1}, "videos": {"v.mp4": video}}
        same = compare(profile([]), profile([], cpu=0.5))
        self.assertTrue(same["identical_alarms"])
        self.assertEqual(same["stages"]["total"]["speedup"], 2)
        self.assertFalse(compare(profile([]), profile(["blur"]))["identical_alarms"])
        with self.assertRaises(ValueError):
            compare(profile([]), profile([], sha="y"))
        empty = profile([])
        empty["videos"]["v.mp4"]["detections"] = []
        with self.assertRaises(ValueError):
            compare(empty, profile([]))


if __name__ == "__main__":
    unittest.main()
