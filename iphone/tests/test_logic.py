import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logic import (MODES, clean_settings, human_delay, in_active_hours, is_paid, load_settings, load_state,  # noqa: E402
                   run_limits, save_settings, save_state, schedule_due)


class PaidButtons(unittest.TestCase):   # AGENTS.md: tryk aldrig på en betalt knap
    def test_paid(self):
        for name in ("Send en rose", "send a Rose", "Rose", "Roser", "Giv en rose", "Boost", "Super Boost"):
            self.assertTrue(is_paid(name), name)

    def test_not_paid(self):
        for name in ("Synes godt om Roses billede", "Like Rose's photo", "Send synes godt om", "Jeg er enig", "Afslut", "Discover"):
            self.assertFalse(is_paid(name), name)

    def test_settings_reject_paid_and_too_short_names(self):
        defaults = clean_settings({})["buttons"]
        for buttons in ({"like_prefix": "Send"}, {"like_prefix": "S"}, {"like_prefix": "Ro"}, {"like_prefix": "Send en rose"},
                        {"send_like": "Send a Rose"}, {"send_like": "Boost"}, {"close": "  x "}):
            self.assertEqual(clean_settings({"buttons": buttons})["buttons"], defaults, buttons)


class Modes(unittest.TestCase):
    def test_three_modes_ordered_by_speed(self):
        self.assertEqual(set(MODES), {"secure", "human", "fast"})
        self.assertLess(MODES["secure"]["daily"], MODES["human"]["daily"])
        self.assertLess(MODES["human"]["daily"], MODES["fast"]["daily"])
        self.assertGreater(MODES["secure"]["delay"][0], MODES["fast"]["delay"][0])

    def test_human_keeps_project_defaults(self):   # AGENTS.md: 80/dag, 30 min
        self.assertEqual((MODES["human"]["daily"], MODES["human"]["minutes"]), (80, 30))

    def test_ranges_are_valid(self):
        for m in MODES.values():
            for lo, hi in (m["delay"], m["pause"], m["every"]):
                self.assertLessEqual(lo, hi)
            self.assertTrue(0 <= m["read"] <= 1)


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
            self.assertEqual(load_state(p, "2026-01-01"), {"date": "2026-01-01", "likes_today": 0, "history": {}})
            p.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_state(p, "2026-01-01")["likes_today"], 0)

    def test_roundtrip_and_new_day_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            save_state(p, {"date": "2026-01-01", "likes_today": 42})
            self.assertEqual(load_state(p, "2026-01-01")["likes_today"], 42)
            self.assertEqual(load_state(p, "2026-01-02")["likes_today"], 0)

    def test_new_day_moves_count_to_history(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            save_state(p, {"date": "2026-01-01", "likes_today": 42, "history": {"2025-12-31": 7, "bad": "x"}})
            state = load_state(p, "2026-01-02")
            self.assertEqual(state["history"], {"2025-12-31": 7, "2026-01-01": 42})
            self.assertEqual(state["likes_today"], 0)

    def test_history_is_capped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "state.json"
            days = {(dt.date(2025, 1, 1) + dt.timedelta(days=i)).isoformat(): 1 for i in range(200)}
            save_state(p, {"date": "2026-01-01", "likes_today": 0, "history": days})
            history = load_state(p, "2026-01-01")["history"]
            self.assertEqual(len(history), 120)
            self.assertIn(max(days), history)   # de nyeste dage beholdes


class Settings(unittest.TestCase):
    def test_defaults(self):
        s = clean_settings(None)
        self.assertEqual((s["lang"], s["mode"], s["from_hour"], s["to_hour"]), ("da", "human", 8, 23))
        self.assertFalse(s["accepted_terms"])
        self.assertFalse(s["schedule"]["enabled"])

    def test_rejects_invalid_values(self):
        s = clean_settings({"lang": "xx", "mode": "turbo", "from_hour": 99, "to_hour": "abc", "accepted_terms": "yes",
                            "limits": {"fast": {"daily": 5000, "minutes": 0}, "nope": {"daily": 10}},
                            "buttons": {"send_like": "a\nb", "close": "  "},
                            "schedule": {"enabled": 1, "time": "25:00", "mode": "x", "last_run": "i går"}})
        self.assertEqual((s["lang"], s["mode"], s["from_hour"], s["to_hour"]), ("da", "human", 8, 23))
        self.assertFalse(s["accepted_terms"])
        self.assertEqual(s["limits"], {})
        self.assertEqual(s["buttons"]["send_like"], "Send synes godt om")
        self.assertEqual(s["buttons"]["close"], "Afslut")
        self.assertEqual(s["schedule"], {"enabled": False, "time": "18:00", "mode": "human", "last_run": ""})

    def test_keeps_valid_values(self):
        s = clean_settings({"lang": "en", "mode": "secure", "from_hour": 0, "to_hour": 24, "accepted_terms": True,
                            "limits": {"fast": {"daily": 300}},
                            "buttons": {"like_prefix": "Like ", "send_like": " Send like "},
                            "schedule": {"enabled": True, "time": "07:30", "mode": "fast", "last_run": "2026-01-01"}})
        self.assertEqual((s["lang"], s["mode"], s["from_hour"], s["to_hour"]), ("en", "secure", 0, 24))
        self.assertTrue(s["accepted_terms"])
        self.assertEqual(s["limits"], {"fast": {"daily": 300}})
        self.assertEqual(s["buttons"]["like_prefix"], "Like ")   # mellemrummet til sidst er en del af præfikset
        self.assertEqual(s["buttons"]["send_like"], "Send like")
        self.assertEqual(s["schedule"], {"enabled": True, "time": "07:30", "mode": "fast", "last_run": "2026-01-01"})

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            self.assertEqual(load_settings(p), clean_settings({}))
            save_settings(p, {"mode": "fast", "limits": {"fast": {"minutes": 60}}})
            s = load_settings(p)
            self.assertEqual(s["mode"], "fast")
            self.assertEqual(run_limits(s, "fast"), (200, 60))
            self.assertEqual(run_limits(s, "human"), (80, 30))


class Schedule(unittest.TestCase):
    sched = {"enabled": True, "time": "18:00", "mode": "human", "last_run": ""}

    def test_due_in_window_only(self):
        self.assertTrue(schedule_due(self.sched, dt.datetime(2026, 1, 1, 18, 0)))
        self.assertTrue(schedule_due(self.sched, dt.datetime(2026, 1, 1, 18, 30)))
        self.assertFalse(schedule_due(self.sched, dt.datetime(2026, 1, 1, 17, 59)))
        self.assertFalse(schedule_due(self.sched, dt.datetime(2026, 1, 1, 18, 31)))

    def test_once_per_day_and_disabled(self):
        self.assertFalse(schedule_due({**self.sched, "last_run": "2026-01-01"}, dt.datetime(2026, 1, 1, 18, 5)))
        self.assertTrue(schedule_due({**self.sched, "last_run": "2025-12-31"}, dt.datetime(2026, 1, 1, 18, 5)))
        self.assertFalse(schedule_due({**self.sched, "enabled": False}, dt.datetime(2026, 1, 1, 18, 5)))


if __name__ == "__main__":
    unittest.main()
