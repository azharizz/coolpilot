import unittest

from experiments.autopilot import bounded


class AutopilotBounds(unittest.TestCase):
    def test_agent_settings_stay_inside_the_published_space(self):
        self.assertEqual(bounded({"adaptive_k": 3, "glare_tiles": 2}), {"adaptive_k": 3, "glare_tiles": 2})
        for bad in ({"adaptive_k": 99}, {"glare_tiles": 7}, {"max_false_alarms_per_hour": 1000}, {"dark_mean": 0}):
            with self.assertRaises(ValueError):
                bounded(bad)
