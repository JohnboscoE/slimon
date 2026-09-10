"""Perception: turn live-venue market data into discrete, timestamped events.

Every detector is deterministic and runs on closed candles only, so an event can be
re-derived from the recorded candle timestamp and is provably not retrospective.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from .broker import Portfolio
from .journal import State, iso
from .market import MarketSnapshot, us_session

SESSION_EDGES = {("pre", "regular"): "us_regular_open", ("regular", "post"): "us_regular_close"}
MIN_BASELINE_CANDLES = 12  # one hour of same-session 5m candles


def _ts(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def _event(etype: str, symbol: str | None, key: str, now: datetime, session: str,
           summary: str, payload: dict, source_ts: int | None = None) -> dict:
    return {
        "id": f"evt-{etype}-{symbol or 'mkt'}-{key}",
        "type": etype,
        "symbol": symbol,
        "received_at": iso(now),
        "source_ts": iso(datetime.fromtimestamp(source_ts / 1000, now.tzinfo)) if source_ts else None,
        "session": session,
        "summary": summary,
        "payload": payload,
    }


class Perception:
    def __init__(self, cfg: dict, state: State):
        self.cfg = cfg
        self.state = state

    def _cooled(self, etype: str, symbol: str | None, now: datetime) -> bool:
        last = self.state.get("event_last", {}).get(f"{etype}|{symbol}")
        if last and now - datetime.fromisoformat(last.replace("Z", "+00:00")) < timedelta(minutes=self.cfg["event_cooldown_minutes"]):
            return False
        return True

    def _mark(self, ev: dict, now: datetime) -> None:
        self.state.get("event_last", {})[f"{ev['type']}|{ev['symbol']}"] = iso(now)

    def detect(self, snap: MarketSnapshot, portfolio: Portfolio, now: datetime, session: str) -> list[dict]:
        events: list[dict] = []
        cfg = self.cfg
        w = cfg["move_window_candles"]

        for sym, view in snap.views.items():
            c = view.candles
            if len(c) < w + 1:
                continue
            last = c[-1]

            ret = (last.close / c[-1 - w].close - 1) * 100
            if abs(ret) >= cfg["move_threshold_pct"] and self._cooled("price_move", sym, now):
                events.append(_event(
                    "price_move", sym, str(last.ts), now, session,
                    f"{sym} {'+' if ret > 0 else ''}{ret:.2f}% over {w * 5}m on the live venue",
                    {"window_min": w * 5, "return_pct": round(ret, 3), "from": c[-1 - w].close, "to": last.close},
                    last.ts))

            # Range/volume baselines use only candles from the same US session as the latest
            # one; otherwise every cash open looks like a spike against thin pre-market candles.
            last_session = us_session(_ts(last.ts))
            prior = [x for x in c[:-1] if us_session(_ts(x.ts)) == last_session]
            if len(prior) < MIN_BASELINE_CANDLES:
                continue

            atr = statistics.fmean(x.high - x.low for x in prior)
            rng = last.high - last.low
            if atr > 0 and rng >= cfg["range_atr_multiple"] * atr and self._cooled("range_expansion", sym, now):
                events.append(_event(
                    "range_expansion", sym, str(last.ts), now, session,
                    f"{sym} 5m range {rng / atr:.1f}x its {len(prior)}-candle average",
                    {"range": rng, "avg_range": round(atr, 6), "multiple": round(rng / atr, 2),
                     "candle": {"o": last.open, "h": last.high, "l": last.low, "c": last.close}},
                    last.ts))

            med_vol = statistics.median(x.volume for x in prior)
            if med_vol > 0 and last.volume >= cfg["volume_multiple"] * med_vol and self._cooled("volume_spike", sym, now):
                events.append(_event(
                    "volume_spike", sym, str(last.ts), now, session,
                    f"{sym} 5m volume {last.volume / med_vol:.1f}x median",
                    {"volume": last.volume, "median_volume": med_vol, "multiple": round(last.volume / med_vol, 2),
                     "candle_return_pct": round((last.close / last.open - 1) * 100, 3)},
                    last.ts))

        # Scheduled events: US cash-session boundaries (first tick after the edge).
        prev_session = self.state.data.get("last_session")
        edge = SESSION_EDGES.get((prev_session, session))
        if edge:
            day = now.strftime("%Y-%m-%d")
            events.append(_event(
                edge, None, day, now, session,
                f"US regular session {'opened' if edge.endswith('open') else 'closed'}",
                {"cross_section": [v.summary() for v in snap.views.values()]}))
        self.state.data["last_session"] = session

        # Held positions: periodic review and PnL band crossings go back to the model.
        reviews = self.state.get("position_reviews", {})
        for p in portfolio.positions:
            band = int(p.pnl_pct / cfg["position_pnl_band_pct"])
            r = reviews.get(p.symbol)
            if r is None:
                reviews[p.symbol] = {"last_at": iso(now), "band": band}
                continue
            age = now - datetime.fromisoformat(r["last_at"].replace("Z", "+00:00"))
            reason = None
            if band != r["band"]:
                reason = f"unrealized PnL moved to {p.pnl_pct:+.2f}%"
            elif age >= timedelta(hours=cfg["position_review_hours"]):
                reason = f"periodic review ({age.total_seconds() / 3600:.1f}h since last)"
            if reason:
                events.append(_event(
                    "position_review", p.symbol, now.strftime("%Y%m%dT%H%M"), now, session,
                    f"{p.symbol} {p.side} position: {reason}",
                    {"side": p.side, "qty": p.qty, "avg_price": p.avg_price, "mark": p.mark_price,
                     "pnl_pct": round(p.pnl_pct, 3), "opened_at": p.opened_at}))
                reviews[p.symbol] = {"last_at": iso(now), "band": band}
        for sym in [s for s in reviews if not portfolio.position(s)]:
            del reviews[sym]

        for ev in events:
            self._mark(ev, now)
        return events
