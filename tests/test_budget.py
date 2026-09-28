import unittest
from datetime import datetime, timedelta, timezone

from slimon.budget import exhausted, record, roll

LIMITS = {"max_calls_per_day": 80, "max_calls_per_day_closed": 12, "max_cost_usd_per_day": 0.60}
NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)


class DailyCap(unittest.TestCase):
    def test_fresh_budget_allows_calls(self):
        b = roll({}, NOW)
        self.assertEqual((b["day"], b["calls"], b["calls_closed"], b["cost_usd"]), ("2026-09-16", 0, 0, 0.0))
        self.assertIsNone(exhausted(b, LIMITS, "regular"))

    def test_session_cap_stops_further_calls(self):
        b = roll({}, NOW)
        for _ in range(79):
            record(b, None, "regular")
        self.assertIsNone(exhausted(b, LIMITS, "regular"))
        record(b, None, "pre")
        self.assertIn("80 model calls in open sessions today (cap 80)", exhausted(b, LIMITS, "post"))

    def test_the_quiet_hours_cannot_spend_the_sessions_allowance(self):
        # The failure this split exists to prevent: an overnight position exhausting the day.
        b = roll({}, NOW)
        for _ in range(12):
            record(b, None, "closed")
        self.assertIn("with the market shut", exhausted(b, LIMITS, "closed"))
        self.assertIsNone(exhausted(b, LIMITS, "regular"))
        self.assertEqual((b["calls_closed"], b["calls"]), (12, 0))

    def test_and_the_session_cannot_spend_the_quiet_hours_allowance(self):
        b = roll({}, NOW)
        for _ in range(80):
            record(b, None, "regular")
        self.assertIsNotNone(exhausted(b, LIMITS, "regular"))
        self.assertIsNone(exhausted(b, LIMITS, "closed"))

    def test_cost_cap_stops_calls_in_any_session(self):
        b = roll({}, NOW)
        record(b, 0.61, "regular")
        self.assertIn("cap $0.6", exhausted(b, LIMITS, "regular"))
        self.assertIn("cap $0.6", exhausted(b, LIMITS, "closed"))

    def test_counters_reset_at_the_utc_day_turn(self):
        b = roll({}, NOW)
        for _ in range(80):
            record(b, 0.01, "regular")
        for _ in range(12):
            record(b, 0.0, "closed")
        self.assertIsNotNone(exhausted(b, LIMITS, "regular"))
        roll(b, NOW + timedelta(days=1))
        self.assertEqual((b["calls"], b["calls_closed"], b["cost_usd"]), (0, 0, 0.0))
        self.assertIsNone(exhausted(b, LIMITS, "regular"))

    def test_no_limits_configured_never_blocks(self):
        b = roll({}, NOW)
        for _ in range(500):
            record(b, 1.0, "regular")
        self.assertIsNone(exhausted(b, {}, "regular"))


if __name__ == "__main__":
    unittest.main()
