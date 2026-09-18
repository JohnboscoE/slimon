import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from slimon.broker import Portfolio, Position
from slimon.market import MarketSnapshot, SymbolView
from slimon.risk import RiskBook, RiskContext, evaluate, forced_actions

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)  # 11:00 New York, regular session
LIMITS = {
    "min_confidence": 0.55, "max_order_notional_usdt": 1500, "max_position_pct_equity": 15,
    "max_gross_exposure_pct_equity": 40, "max_open_positions": 3, "leverage": 2,
    "daily_drawdown_halt_pct": 3.0, "consecutive_loss_limit": 3, "loss_cooldown_minutes": 240,
    "max_trades_per_day": 8, "symbol_min_minutes_between_trades": 60, "max_spread_pct": 0.30,
    "max_live_demo_divergence_pct": 1.5, "stop_loss_pct": 2.5, "take_profit_pct": 5.0, "max_holding_hours": 72,
    "open_sessions": ["pre", "regular", "post"],
}
META = {"status": "online", "quantityMultiplier": "0.01", "quantityPrecision": "2",
        "pricePrecision": "2", "minOrderQty": "0.01", "minOrderAmount": "5"}
WHITELIST = ["NVDAUSDT", "AAPLUSDT"]


def view(symbol="NVDAUSDT", live=220.0, demo=221.0, bid=220.95, ask=221.05, meta=META):
    return SymbolView(symbol, [], {"lastPrice": str(live)},
                      {"markPrice": str(demo), "bid1Price": str(bid), "ask1Price": str(ask)}, dict(meta))


def ctx(positions=(), equity=10_000.0, session="regular", kill=False, book=None, views=None, now=NOW):
    views = views or {"NVDAUSDT": view(), "AAPLUSDT": view("AAPLUSDT", 230, 230.5, 230.45, 230.55),
                      "COINUSDT": view("COINUSDT", 300, 300.2, 300.1, 300.3)}
    book = book or RiskBook({}, LIMITS)
    book.roll_day(now, equity)
    return RiskContext(now=now, session=session, portfolio=Portfolio("test", equity, 0.0, list(positions)),
                       snap=MarketSnapshot(now, views, []), whitelist=WHITELIST, limits=LIMITS, book=book,
                       kill_switch=kill, event_ids={"evt-1", "evt-2"})


def decision(**kw):
    d = {"action": "OPEN_LONG", "instrument": "NVDAUSDT", "notional_usdt": 1000.0, "confidence": 0.7,
         "time_horizon_hours": 6, "triggering_event_ids": ["evt-1"], "reasoning": "r", "invalidation": "i"}
    d.update(kw)
    return d


def failed(result):
    return {c["check"] for c in result["checks"] if not c["passed"]}


def pos(symbol="NVDAUSDT", side="long", qty=4.0, avg=221.0, mark=221.0, opened=NOW - timedelta(hours=1)):
    d = 1 if side == "long" else -1
    return Position(symbol, side, qty, avg, mark, (mark - avg) * qty * d, opened.isoformat())


class GatePasses(unittest.TestCase):
    def test_clean_open_passes_with_sized_intent(self):
        r = evaluate(decision(), ctx())
        self.assertEqual(r["verdict"], "PASS", r["veto_reasons"])
        i = r["intent"]
        self.assertEqual((i["side"], i["pos_side"], i["reduce_only"]), ("buy", "long", False))
        self.assertEqual(i["qty"], "4.52")                       # floor(1000 / 221, 0.01)
        self.assertAlmostEqual(i["stop_loss_price"], 215.475, delta=0.01)  # 221 * (1 - 2.5%), 2dp
        self.assertTrue(all(c["passed"] for c in r["checks"]))

    def test_short_stop_is_above_entry(self):
        r = evaluate(decision(action="OPEN_SHORT"), ctx())
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["intent"]["side"], "sell")
        self.assertGreater(r["intent"]["stop_loss_price"], 221.0)

    def test_no_trade_is_no_action(self):
        r = evaluate(decision(action="NO_TRADE", instrument="", notional_usdt=0), ctx())
        self.assertEqual(r["verdict"], "NO_ACTION")
        self.assertIsNone(r["intent"])


class GateVetoes(unittest.TestCase):
    def assertVeto(self, result, check):
        self.assertEqual(result["verdict"], "VETO")
        self.assertIn(check, failed(result))
        self.assertIsNone(result["intent"])
        self.assertTrue(any(v.startswith(check) for v in result["veto_reasons"]))

    def test_not_whitelisted(self):
        self.assertVeto(evaluate(decision(instrument="COINUSDT"), ctx()), "whitelist")

    def test_hallucinated_event_id(self):
        self.assertVeto(evaluate(decision(triggering_event_ids=["evt-made-up"]), ctx()), "schema.event_ids_grounded")

    def test_no_event_ids(self):
        self.assertVeto(evaluate(decision(triggering_event_ids=[]), ctx()), "schema.event_ids_grounded")

    def test_malformed_numbers(self):
        for bad in (math.nan, math.inf, -5.0, 0.0):
            self.assertVeto(evaluate(decision(notional_usdt=bad), ctx()), "schema.notional_sane")
        self.assertVeto(evaluate(decision(confidence=1.7), ctx()), "schema.confidence_range")
        self.assertVeto(evaluate(decision(confidence=math.nan), ctx()), "schema.confidence_range")

    def test_low_confidence(self):
        self.assertVeto(evaluate(decision(confidence=0.4), ctx()), "min_confidence")

    def test_order_notional_cap(self):
        self.assertVeto(evaluate(decision(notional_usdt=5000), ctx()), "max_order_notional")

    def test_position_cap_counts_existing(self):
        # 15% of 10k = 1500; existing ~884 + 1000 breaches it
        self.assertVeto(evaluate(decision(), ctx(positions=[pos()])), "position_cap")

    def test_gross_exposure_cap(self):
        held = [pos("AAPLUSDT", qty=10, avg=230.5, mark=230.5), pos("COINUSDT", qty=5, avg=300.2, mark=300.2)]
        r = evaluate(decision(notional_usdt=1400), ctx(positions=held))  # 2305 + 1501 + 1400 > 4000
        self.assertVeto(r, "gross_exposure_cap")

    def test_max_open_positions(self):
        held = [pos("AAPLUSDT", qty=1), pos("COINUSDT", qty=1), pos("XUSDT", qty=1)]
        self.assertVeto(evaluate(decision(notional_usdt=100), ctx(positions=held)), "max_open_positions")

    def test_reversal_requires_close(self):
        self.assertVeto(evaluate(decision(action="OPEN_SHORT", notional_usdt=100), ctx(positions=[pos(qty=1)])),
                        "direction_conflict")

    def test_session_closed(self):
        self.assertVeto(evaluate(decision(), ctx(session="closed")), "session_open")

    def test_kill_switch(self):
        self.assertVeto(evaluate(decision(), ctx(kill=True)), "kill_switch")

    def test_wide_spread(self):
        v = {"NVDAUSDT": view(bid=219.0, ask=223.0)}
        self.assertVeto(evaluate(decision(), ctx(views=v)), "spread_sanity")

    def test_venue_divergence(self):
        v = {"NVDAUSDT": view(live=200.0)}
        self.assertVeto(evaluate(decision(), ctx(views=v)), "venue_divergence")

    def test_instrument_offline(self):
        v = {"NVDAUSDT": view(meta={**META, "status": "limit_open"})}
        self.assertVeto(evaluate(decision(), ctx(views=v)), "instrument_online")

    def test_below_min_order_size(self):
        self.assertVeto(evaluate(decision(notional_usdt=1.0), ctx()), "min_order_size")

    def test_trade_spacing_and_daily_count(self):
        book = RiskBook({}, LIMITS)
        book.roll_day(NOW, 10_000)
        book.record_trade("NVDAUSDT", NOW - timedelta(minutes=10))
        self.assertVeto(evaluate(decision(notional_usdt=100), ctx(book=book)), "symbol_trade_spacing")
        book.d["trades_today"] = 8
        self.assertVeto(evaluate(decision(instrument="AAPLUSDT", notional_usdt=100), ctx(book=book)),
                        "max_trades_per_day")


class Breakers(unittest.TestCase):
    def test_drawdown_breaker_trips_blocks_opens_allows_close(self):
        book = RiskBook({}, LIMITS)
        book.roll_day(NOW, 10_000)
        trip = book.update_breaker(NOW, 9_650)                     # -3.5%
        self.assertEqual(trip["type"], "drawdown_breaker_tripped")
        self.assertTrue(book.halted(NOW))
        self.assertFalse(book.halted(NOW + timedelta(days=1)))    # resets at next UTC midnight
        c = ctx(equity=9_650, book=book, positions=[pos(qty=1)])
        r = evaluate(decision(instrument="AAPLUSDT", notional_usdt=100), c)
        self.assertIn("daily_drawdown_breaker", failed(r))
        close = evaluate(decision(action="CLOSE", notional_usdt=0), c)
        self.assertEqual(close["verdict"], "PASS")
        self.assertTrue(close["intent"]["reduce_only"])
        self.assertEqual(close["intent"]["side"], "sell")

    def test_consecutive_losses_start_cooldown(self):
        book = RiskBook({}, LIMITS)
        book.roll_day(NOW, 10_000)
        notes = book.record_closed([{"pnl": -10}, {"pnl": -5}, {"pnl": -1}], NOW)
        self.assertEqual(notes[0]["type"], "loss_cooldown_started")
        self.assertTrue(book.in_cooldown(NOW + timedelta(minutes=239)))
        self.assertFalse(book.in_cooldown(NOW + timedelta(minutes=241)))
        self.assertIn("loss_cooldown", failed(evaluate(decision(), ctx(book=book))))

    def test_win_resets_loss_streak(self):
        book = RiskBook({}, LIMITS)
        book.record_closed([{"pnl": -10}, {"pnl": -5}, {"pnl": 3}, {"pnl": -1}], NOW)
        self.assertEqual(book.d["consecutive_losses"], 1)
        self.assertFalse(book.in_cooldown(NOW))

    def test_close_without_position_is_vetoed(self):
        r = evaluate(decision(action="CLOSE", notional_usdt=0), ctx())
        self.assertEqual(r["verdict"], "VETO")
        self.assertIn("close.position_exists", failed(r))


class Forced(unittest.TestCase):
    def test_hard_stop(self):
        f = forced_actions(ctx(positions=[pos(avg=221.0, mark=215.0)]))  # -2.7%
        self.assertEqual([x["rule"] for x in f], ["hard_stop"])
        self.assertTrue(f[0]["intent"]["reduce_only"])

    def test_short_hard_stop(self):
        f = forced_actions(ctx(positions=[pos(side="short", avg=221.0, mark=227.0)]))
        self.assertEqual([x["rule"] for x in f], ["hard_stop"])
        self.assertEqual(f[0]["intent"]["side"], "buy")

    def test_max_holding_time(self):
        f = forced_actions(ctx(positions=[pos(opened=NOW - timedelta(hours=73))]))
        self.assertEqual([x["rule"] for x in f], ["max_holding_time"])

    def test_healthy_position_left_alone(self):
        self.assertEqual(forced_actions(ctx(positions=[pos(mark=223.0)])), [])


class JournalScrub(unittest.TestCase):
    def test_secret_never_written(self):
        import slimon.journal as j
        with tempfile.TemporaryDirectory() as d:
            orig = j.LOG_DIR
            j.LOG_DIR = Path(d)
            try:
                j.Journal(["sk-super-secret-value"]).tick({"oops": "key=sk-super-secret-value"}, NOW)
                text = next(Path(d).rglob("*.jsonl")).read_text()
            finally:
                j.LOG_DIR = orig
        self.assertNotIn("sk-super-secret-value", text)
        self.assertIn("[REDACTED]", text)


if __name__ == "__main__":
    unittest.main()
