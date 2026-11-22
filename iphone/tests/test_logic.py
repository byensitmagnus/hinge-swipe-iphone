import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logic import human_delay, in_active_hours, load_state, save_state  # noqa: E402


class HumanDelay(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(human_delay(0.0, 0.5), 5.0)
        self.assertEqual(human_delay(1.0, 0.5), 12.0)
        self.assertAlmostEqual(human_delay(0.5, 0.0), 8.5)

    def test_never_instant(self):
        self.assertGreaterEqual(human_delay(-5, 0.0), 5.0)

    def test_rare_long_pause(self):
        self.assertGreater(human_delay(0.0, 1.0), 12.0)
        self.assertLessEqual(human_delay(0.0, 1.0), 5.0 + 36.0)


class ActiveHours(unittest.TestCase):
    def test_day_window(self):
        self.assertTrue(in_active_hours(8, 8, 23) and in_active_hours(22, 8, 23))
        self.assertFalse(in_active_hours(23, 8, 23) or in_active_hours(3, 8, 23))

    def test_over_midnight(self):
        self.assertTrue(in_active_hours(23, 20, 4) and in_active_hours(2, 20, 4))
        self.assertFalse(in_active_hours(12, 20, 4))

    def test_whole_day(self):
        self.assertTrue(in_active_hours(3, 0, 24) and in_active_hours(3, 5, 5))


class State(unittest.TestCase):
    def test_missing_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            self.assertEqual(load_state(p, "2026-01-01"), {"date": "2026-01-01", "likes_today": 0})
            p.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_state(p, "2026-01-01")["likes_today"], 0)

    def test_roundtrip_and_new_day_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            save_state(p, {"date": "2026-01-01", "likes_today": 42})
            self.assertEqual(load_state(p, "2026-01-01")["likes_today"], 42)
            self.assertEqual(load_state(p, "2026-01-02")["likes_today"], 0)


if __name__ == "__main__":
    unittest.main()
