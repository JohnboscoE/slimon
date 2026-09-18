"""Exits: the preset target and stop, the gate's own closes, and a recorded reason for each."""
import unittest
from datetime import datetime, timedelta, timezone

from slimon.market import MarketSnapshot
from slimon.perception import Perception
from slimon.risk import forced_actions

from test_risk import LIMITS, META, NOW, ctx, decision, evaluate, pos, view


class PresetTargetAndStop(unittest.TestCase):
    def test_a_long_carries_both_prices(self):
        r = evaluate(decision(), ctx())
        self.assertEqual(r["verdict"], "PASS")
        intent = r["intent"]
        # demo price 221, stop 2.5% below, target 5% above
        self.assertAlmostEqual(intent["stop_loss_price"], round(221 * 0.975, 2), places=2)
        self.assertAlmostEqual(intent["take_profit_price"], round(221 * 1.05, 2), places=2)

    def test_a_short_has_them_the_other_way_round(self):
        r = evaluate(decision(action="OPEN_SHORT"), ctx())
        intent = r["intent"]
        self.assertGreater(intent["stop_loss_price"], intent["ref_price"])
        self.assertLess(intent["take_profit_price"], intent["ref_price"])

    def test_no_target_configured_means_none_sent(self):
        limits = {**LIMITS, "take_profit_pct": 0}
        c = ctx()
        c.limits = limits
        self.assertIsNone(evaluate(decision(), c)["intent"]["take_profit_price"])


class GateInitiatedExits(unittest.TestCase):
    def test_a_winner_past_the_target_is_closed_with_its_reason(self):
        winner = pos(mark=221 * 1.06)  # +6% against a 5% target
        actions = forced_actions(ctx(positions=[winner]))
        self.assertEqual([a["rule"] for a in actions], ["take_profit"])
        self.assertIn("+6.00% >= +5.0%", actions[0]["detail"])
        self.assertEqual(actions[0]["intent"]["reason"], "take_profit")
        self.assertTrue(actions[0]["intent"]["reduce_only"])

    def test_a_loser_past_the_stop_is_closed_first(self):
        loser = pos(mark=221 * 0.97)
        actions = forced_actions(ctx(positions=[loser]))
        self.assertEqual([a["rule"] for a in actions], ["hard_stop"])

    def test_a_position_between_the_two_is_left_alone(self):
        self.assertEqual(forced_actions(ctx(positions=[pos(mark=221 * 1.02)])), [])


class StubState:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, default):
        return self.data.setdefault(key, default)


class MacroCalendar(unittest.TestCase):
    CFG = {"move_window_candles": 6, "move_threshold_pct": 1.0, "range_atr_multiple": 3.0,
           "volume_multiple": 4.0, "event_cooldown_minutes": 60, "position_review_hours": 4,
           "position_pnl_band_pct": 1.5,
           "macro_events": [{"at": "2026-09-10T18:00:00Z", "name": "FOMC rate decision"}]}

    def detect(self, now, state=None):
        p = Perception(self.CFG, state or StubState())
        snap = MarketSnapshot(now, {}, [])
        return p, p.detect(snap, ctx().portfolio, now, "regular")

    def test_fires_once_at_the_scheduled_time(self):
        at = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)
        state = StubState()
        p, events = self.detect(at + timedelta(minutes=2), state)
        self.assertEqual([e["type"] for e in events], ["macro_event"])
        self.assertIn("FOMC rate decision", events[0]["summary"])
        self.assertIsNone(events[0]["symbol"])  # market-wide, so the model is consulted
        # A second tick inside the window does not repeat it.
        _, again = self.detect(at + timedelta(minutes=5), state)
        self.assertEqual(again, [])

    def test_does_not_fire_before_the_time_or_long_after(self):
        at = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)
        _, early = self.detect(at - timedelta(minutes=5))
        self.assertEqual(early, [])
        _, late = self.detect(at + timedelta(hours=3))
        self.assertEqual(late, [])


if __name__ == "__main__":
    unittest.main()
