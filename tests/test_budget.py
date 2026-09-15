import unittest
from datetime import datetime, timedelta, timezone

from slimon.budget import exhausted, record, roll

LIMITS = {"max_calls_per_day": 40, "max_cost_usd_per_day": 0.05}
NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)


class DailyCap(unittest.TestCase):
    def test_fresh_budget_allows_calls(self):
        b = roll({}, NOW)
        self.assertEqual((b["day"], b["calls"], b["cost_usd"]), ("2026-09-16", 0, 0.0))
        self.assertIsNone(exhausted(b, LIMITS))

    def test_call_cap_stops_further_calls(self):
        b = roll({}, NOW)
        for _ in range(39):
            record(b, None)
        self.assertIsNone(exhausted(b, LIMITS))
        record(b, None)
        self.assertIn("40 model calls today (cap 40)", exhausted(b, LIMITS))

    def test_cost_cap_stops_further_calls(self):
        b = roll({}, NOW)
        record(b, 0.03)
        self.assertIsNone(exhausted(b, LIMITS))
        record(b, 0.02)
        self.assertIn("cap $0.05", exhausted(b, LIMITS))

    def test_counters_reset_at_the_utc_day_turn(self):
        b = roll({}, NOW)
        for _ in range(40):
            record(b, 0.01)
        self.assertIsNotNone(exhausted(b, LIMITS))
        roll(b, NOW + timedelta(days=1))
        self.assertEqual((b["calls"], b["cost_usd"]), (0, 0.0))
        self.assertIsNone(exhausted(b, LIMITS))

    def test_no_limits_configured_never_blocks(self):
        b = roll({}, NOW)
        for _ in range(500):
            record(b, 1.0)
        self.assertIsNone(exhausted(b, {}))


if __name__ == "__main__":
    unittest.main()
