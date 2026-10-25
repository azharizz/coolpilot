import unittest

from experiments.autopilot import bounded


class AutopilotBounds(unittest.TestCase):
    def test_agent_settings_stay_inside_the_published_space(self):
        self.assertEqual(bounded({"adaptive_k": 3, "glare_tiles": 2}), {"adaptive_k": 3, "glare_tiles": 2})
        for bad in ({"adaptive_k": 99}, {"glare_tiles": 7}, {"max_false_alarms_per_hour": 1000}, {"dark_mean": 0}):
            with self.assertRaises(ValueError):
                bounded(bad)


class AutopilotAblate(unittest.TestCase):
    def test_ablate_returns_what_it_measured_when_the_budget_runs_out(self):
        from experiments.autopilot import Session, call
        session = Session(budget=2)

        def score(settings):
            session.used += 1
            return {"oxford_failed_checks": [], "drivec_dev_passed": 10, "drivec_false_alarms": 0, "passed_by_class_of_25": {}}
        session.score = score
        out = call(session, "ablate", {"settings": {}, "name": "adaptive_k", "values": [1, 2, 3]}, {"ablate"})
        self.assertEqual([r["value"] for r in out["results"]], [1, 2])
        self.assertIn("budget", out["stopped"])
