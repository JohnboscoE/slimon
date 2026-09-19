import unittest

from slimon.agent import _for_model, positions_to_track, worth_a_decision
from slimon.broker import Portfolio, Position
from slimon.risk import RiskBook

from test_risk import LIMITS, NOW, pos


class FakeHistoryBroker:
    """detect_closed as BitgetBroker implements it, with the venue's position history stubbed."""

    def __init__(self, pnl_by_symbol):
        from slimon.broker import BitgetBroker
        self._impl = BitgetBroker.detect_closed
        self.managed = set(pnl_by_symbol)
        self.category = "USDT-FUTURES"
        self.client = type("C", (), {"position_history": lambda _, cat, sym, limit=1: [{"netProfit": str(pnl_by_symbol[sym])}]})()

    def detect_closed(self, prev, portfolio):
        return self._impl(self, prev, portfolio)


class AgentClosesAreRecorded(unittest.TestCase):
    def test_a_position_the_agent_closed_is_still_tracked(self):
        nvda = pos("NVDAUSDT")
        tracked = positions_to_track(held_at_start=[nvda], held_after=[])
        self.assertIn("NVDAUSDT", tracked)

    def test_a_position_opened_this_tick_is_tracked(self):
        self.assertIn("AAPLUSDT", positions_to_track([], [pos("AAPLUSDT")]))

    def test_three_agent_closed_losers_start_the_cooldown(self):
        # The bug: four model-closed losers in a row never reached the loss counter.
        book = RiskBook({}, LIMITS)
        notes = []
        for sym in ("NVDAUSDT", "AAPLUSDT", "TSLAUSDT"):
            broker = FakeHistoryBroker({sym: -12.5})
            prev = positions_to_track(held_at_start=[pos(sym)], held_after=[])  # closed by the agent this tick
            closed = broker.detect_closed(prev, Portfolio("test", 10_000, 0, []))
            self.assertEqual([c["symbol"] for c in closed], [sym])
            notes += book.record_closed(closed, NOW)
        self.assertEqual([n["type"] for n in notes], ["loss_cooldown_started"])
        self.assertTrue(book.in_cooldown(NOW))

WHITELIST = ["NVDAUSDT", "SP500USDT"]


def ev(etype="price_move", symbol="NVDAUSDT", payload=None):
    return {"id": f"evt-{etype}-{symbol}", "type": etype, "symbol": symbol, "payload": payload or {}}


class WorthADecision(unittest.TestCase):
    def test_no_events_never_calls(self):
        self.assertFalse(worth_a_decision([], WHITELIST, holding=False))
        self.assertFalse(worth_a_decision([], WHITELIST, holding=True))

    def test_watch_only_events_alone_are_skipped_when_flat(self):
        self.assertFalse(worth_a_decision([ev(symbol="MSTRUSDT"), ev("volume_spike", "CRCLUSDT")], WHITELIST, holding=False))

    def test_any_tradable_event_calls(self):
        self.assertTrue(worth_a_decision([ev(symbol="MSTRUSDT"), ev(symbol="NVDAUSDT")], WHITELIST, holding=False))

    def test_session_edge_calls(self):
        self.assertTrue(worth_a_decision([ev("us_regular_open", None)], WHITELIST, holding=False))

    def test_watch_only_event_still_calls_while_holding(self):
        # Crypto-proxy weakness can matter to a held position, so the model gets to see it.
        self.assertTrue(worth_a_decision([ev(symbol="MSTRUSDT")], WHITELIST, holding=True))


class ForModel(unittest.TestCase):
    def test_cross_section_is_not_sent_twice(self):
        e = ev("us_regular_close", None, {"cross_section": [{"symbol": "NVDAUSDT"}], "note": "kept"})
        sent = _for_model(e)
        self.assertNotIn("cross_section", sent["payload"])
        self.assertEqual(sent["payload"]["note"], "kept")
        self.assertIn("cross_section", e["payload"])  # the logged event is untouched

    def test_other_events_pass_through(self):
        e = ev(payload={"return_pct": 1.2})
        self.assertIs(_for_model(e), e)


if __name__ == "__main__":
    unittest.main()
