import unittest
from datetime import timedelta

from slimon.broker import BitgetBroker
from slimon.market import MarketSnapshot
from slimon.risk import RiskBook, RiskContext, evaluate, forced_actions

from test_risk import LIMITS, NOW, WHITELIST, decision, failed, view


class FakeClient:
    """Just enough of BitgetClient for a read-only (dry-run) broker."""

    def __init__(self, rows):
        self.rows = rows

    def account_settings(self):
        return {"holdMode": "one_way_mode"}

    def account_assets(self):
        return {"accountEquity": "10000", "unrealisedPnl": "0"}

    def positions(self, category):
        return self.rows


def row(symbol, side, qty, avg, mark, opened=NOW - timedelta(hours=100)):
    return {"symbol": symbol, "posSide": side, "total": str(qty), "avgPrice": str(avg), "markPrice": str(mark),
            "unrealisedPnl": "0", "createdTime": str(int(opened.timestamp() * 1000))}


class ForeignPositions(unittest.TestCase):
    """A position opened outside the agent (by hand, on a symbol it does not trade) must not be managed by it."""

    def setUp(self):
        client = FakeClient([
            row("NVDAUSDT", "long", 4, 221, 221, opened=NOW - timedelta(hours=1)),
            # BTC down 10% and held 100h: would trip both the hard stop and max holding time if it were ours.
            row("BTCUSDT", "long", 0.0158, 77104.6, 69394.1),
        ])
        self.broker = BitgetBroker(client, "USDT-FUTURES", trading=False, leverage=2, symbols=WHITELIST)
        self.snap = MarketSnapshot(NOW, {"NVDAUSDT": view()}, [])
        self.portfolio = self.broker.portfolio(self.snap)

    def ctx(self):
        book = RiskBook({}, LIMITS)
        book.roll_day(NOW, self.portfolio.equity)
        return RiskContext(now=NOW, session="regular", portfolio=self.portfolio, snap=self.snap, whitelist=WHITELIST,
                           limits=LIMITS, book=book, kill_switch=False, event_ids={"evt-1"})

    def test_split_into_managed_and_foreign(self):
        self.assertEqual([p.symbol for p in self.portfolio.positions], ["NVDAUSDT"])
        self.assertEqual([p.symbol for p in self.portfolio.foreign], ["BTCUSDT"])
        self.assertEqual([p["symbol"] for p in self.portfolio.to_dict()["foreign_positions"]], ["BTCUSDT"])

    def test_gate_never_force_closes_a_foreign_position(self):
        self.assertEqual(forced_actions(self.ctx()), [])

    def test_model_cannot_close_a_foreign_position(self):
        r = evaluate(decision(action="CLOSE", instrument="BTCUSDT", notional_usdt=0), self.ctx())
        self.assertEqual(r["verdict"], "VETO")
        self.assertIn("close.position_exists", failed(r))

    def test_foreign_exposure_still_counts_against_gross_cap(self):
        btc = self.portfolio.foreign[0].notional
        self.assertAlmostEqual(self.portfolio.gross_exposure, 4 * 221 + btc, places=6)

    def test_foreign_close_is_not_recorded_as_our_trade(self):
        # State saved by an older build that still tracked the foreign position.
        prev = {"BTCUSDT": {"side": "long", "qty": 0.0158}, "NVDAUSDT": {"side": "long", "qty": 4}}
        self.assertEqual(self.broker.detect_closed(prev, self.portfolio), [])

    def test_order_for_symbol_missing_from_snapshot_does_not_raise(self):
        intent = {"action": "CLOSE", "symbol": "AAPLUSDT", "side": "sell", "pos_side": "long", "qty": "1",
                  "reduce_only": True}
        ex = self.broker.execute(intent, "slmtest", self.snap, NOW, submit=True)
        self.assertEqual(ex["status"], "would_submit")


if __name__ == "__main__":
    unittest.main()
