"""Market snapshot: live-venue candles (the signal) + demo-venue tickers (the execution venue)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from .bitget import BitgetClient, BitgetError

NY = ZoneInfo("America/New_York")
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1H": 3_600_000}


def us_session(now: datetime) -> str:
    """US equity session for `now` (aware datetime). Exchange holidays are not modelled."""
    ny = now.astimezone(NY)
    if ny.weekday() >= 5:
        return "closed"
    t = ny.time()
    if dtime(4, 0) <= t < dtime(9, 30):
        return "pre"
    if dtime(9, 30) <= t < dtime(16, 0):
        return "regular"
    if dtime(16, 0) <= t < dtime(20, 0):
        return "post"
    return "closed"


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SymbolView:
    symbol: str
    candles: list[Candle]          # closed live-venue candles, oldest first
    live: dict | None              # live ticker
    demo: dict | None              # demo ticker
    meta: dict | None              # demo instrument metadata

    def _f(self, src: dict | None, key: str) -> float | None:
        try:
            return float(src[key]) if src and src.get(key) not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @property
    def live_price(self) -> float | None:
        return self._f(self.live, "lastPrice")

    @property
    def demo_price(self) -> float | None:
        return self._f(self.demo, "markPrice") or self._f(self.demo, "lastPrice")

    @property
    def demo_bid(self) -> float | None:
        return self._f(self.demo, "bid1Price")

    @property
    def demo_ask(self) -> float | None:
        return self._f(self.demo, "ask1Price")

    @property
    def demo_spread_pct(self) -> float | None:
        b, a = self.demo_bid, self.demo_ask
        if not b or not a:
            return None
        return (a - b) / ((a + b) / 2) * 100

    @property
    def divergence_pct(self) -> float | None:
        lp, dp = self.live_price, self.demo_price
        if not lp or not dp:
            return None
        return (dp - lp) / lp * 100

    def summary(self) -> dict:
        """Compact, LLM- and log-friendly view."""
        c = self.candles
        def ret(n: int) -> float | None:
            if len(c) <= n or not c[-1 - n].close:
                return None
            return round((c[-1].close / c[-1 - n].close - 1) * 100, 3)
        return {
            "symbol": self.symbol,
            "live_last": self.live_price,
            "live_24h_change_pct": round(self._f(self.live, "price24hPcnt") * 100, 3) if self._f(self.live, "price24hPcnt") is not None else None,
            "ret_30m_pct": ret(6),
            "ret_2h_pct": ret(24),
            "demo_mark": self.demo_price,
            "demo_spread_pct": round(self.demo_spread_pct, 4) if self.demo_spread_pct is not None else None,
            "demo_vs_live_pct": round(self.divergence_pct, 3) if self.divergence_pct is not None else None,
            "funding_rate": self._f(self.live, "fundingRate"),
            "instrument_status": (self.meta or {}).get("status"),
        }


@dataclass
class MarketSnapshot:
    fetched_at: datetime
    views: dict[str, SymbolView]
    errors: list[str]


class Market:
    def __init__(self, client: BitgetClient, category: str, interval: str, lookback: int):
        self.client = client
        self.category = category
        self.interval = interval
        self.lookback = lookback
        self._meta: dict[str, dict] = {}
        self._meta_at = 0.0

    def instrument_meta(self) -> dict[str, dict]:
        if time.time() - self._meta_at > 3600 or not self._meta:
            rows = self.client.instruments(self.category, venue="demo")
            self._meta = {r["symbol"]: r for r in rows}
            self._meta_at = time.time()
        return self._meta

    def snapshot(self, symbols: list[str], now: datetime) -> MarketSnapshot:
        errors: list[str] = []
        def by_symbol(venue: str) -> dict[str, dict]:
            try:
                return {t["symbol"]: t for t in self.client.tickers(self.category, venue=venue)}
            except BitgetError as e:
                errors.append(f"tickers[{venue}]: {e}")
                return {}
        live, demo = by_symbol("live"), by_symbol("demo")
        try:
            meta = self.instrument_meta()
        except BitgetError as e:
            errors.append(f"instruments: {e}")
            meta = self._meta
        now_ms = int(now.timestamp() * 1000)
        step = INTERVAL_MS[self.interval]
        views: dict[str, SymbolView] = {}
        for sym in symbols:
            candles: list[Candle] = []
            try:
                rows = self.client.candles(self.category, sym, self.interval, self.lookback + 2, venue="live")
                for r in rows:
                    c = Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
                    if c.ts + step <= now_ms:  # closed candles only
                        candles.append(c)
                candles.sort(key=lambda c: c.ts)
            except (BitgetError, ValueError, IndexError) as e:
                errors.append(f"candles[{sym}]: {e}")
            views[sym] = SymbolView(sym, candles[-(self.lookback + 1):], live.get(sym), demo.get(sym), meta.get(sym))
        return MarketSnapshot(now, views, errors)
