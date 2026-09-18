"""Account views and order execution.

SimBroker    - local paper book priced off the Bitget demo venue (no key needed).
BitgetBroker - the real Bitget demo account. Orders are sent only when submit=True
               (ENABLE_TRADING=1); otherwise the would-be order is returned unsent.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .bitget import AMBIGUOUS_ORDER_CODES, BitgetClient, BitgetError
from .journal import State, iso
from .market import MarketSnapshot


@dataclass
class Position:
    symbol: str
    side: str            # long | short
    qty: float
    avg_price: float
    mark_price: float
    unrealized_pnl: float
    opened_at: str | None

    @property
    def notional(self) -> float:
        return abs(self.qty * self.mark_price)

    @property
    def pnl_pct(self) -> float:
        if not self.avg_price:
            return 0.0
        d = 1 if self.side == "long" else -1
        return (self.mark_price / self.avg_price - 1) * 100 * d


@dataclass
class Portfolio:
    source: str
    equity: float
    unrealized_pnl: float
    positions: list[Position]
    # Positions in the account on symbols the agent does not trade (opened by hand, say).
    # The agent never reviews, closes or counts them as its own, but their exposure still
    # counts against the gross cap: the margin behind them is real.
    foreign: list[Position] = field(default_factory=list)

    def position(self, symbol: str) -> Position | None:
        return next((p for p in self.positions if p.symbol == symbol), None)

    @property
    def gross_exposure(self) -> float:
        return sum(p.notional for p in self.positions + self.foreign)

    def to_dict(self) -> dict:
        def row(p: Position) -> dict:
            return {**asdict(p), "notional": round(p.notional, 4), "pnl_pct": round(p.pnl_pct, 3)}

        return {
            "source": self.source,
            "equity": round(self.equity, 4),
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "gross_exposure": round(self.gross_exposure, 4),
            "positions": [row(p) for p in self.positions],
            "foreign_positions": [row(p) for p in self.foreign],
        }


def floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


def fmt_decimal(value: float, decimals: int) -> str:
    return f"{value:.{max(decimals, 0)}f}"


# ---------------------------------------------------------------------------


class SimBroker:
    name = "sim"

    def __init__(self, starting_equity: float, fee_rate: float):
        self.state = State("sim_book.json")
        self.book = self.state.get("book", {"cash": starting_equity, "positions": {}, "closed": []})
        self.fee_rate = fee_rate

    def portfolio(self, snap: MarketSnapshot) -> Portfolio:
        positions = []
        for sym, p in self.book["positions"].items():
            view = snap.views.get(sym)
            mark = (view.demo_price if view else None) or p["avg_price"]
            d = 1 if p["side"] == "long" else -1
            upnl = (mark - p["avg_price"]) * p["qty"] * d
            positions.append(Position(sym, p["side"], p["qty"], p["avg_price"], mark, upnl, p["opened_at"]))
        upnl = sum(p.unrealized_pnl for p in positions)
        return Portfolio("sim", self.book["cash"] + upnl, upnl, positions)

    def execute(self, intent: dict, client_oid: str, snap: MarketSnapshot, now: datetime, submit: bool) -> dict:
        view = snap.views[intent["symbol"]]
        buying = intent["side"] == "buy"
        price = (view.demo_ask if buying else view.demo_bid) or view.demo_price
        qty = float(intent["qty"])
        fee = qty * price * self.fee_rate
        sym = intent["symbol"]
        realized = None
        if intent["reduce_only"]:
            p = self.book["positions"].pop(sym)
            d = 1 if p["side"] == "long" else -1
            realized = (price - p["avg_price"]) * p["qty"] * d - fee
            self.book["cash"] += realized  # net of the closing fee
            self.book["closed"].append({"symbol": sym, "side": p["side"], "pnl": realized, "closed_at": iso(now)})
        else:
            self.book["positions"][sym] = {"side": intent["pos_side"], "qty": qty, "avg_price": price,
                                           "opened_at": iso(now)}
            self.book["cash"] -= fee
        self.state.save()
        return {"status": "filled", "venue": "sim", "client_oid": client_oid, "fill_price": price,
                "qty": qty, "fee": round(fee, 6), "realized_pnl": None if realized is None else round(realized, 6)}

    def detect_closed(self, prev: dict, portfolio: Portfolio) -> list[dict]:
        closed, self.book["closed"] = self.book["closed"], []
        self.state.save()
        return closed


# ---------------------------------------------------------------------------


class BitgetBroker:
    name = "bitget_demo"

    def __init__(self, client: BitgetClient, category: str, *, trading: bool, leverage: int, symbols: list[str]):
        self.client = client
        self.category = category
        self.trading = trading
        self.managed = set(symbols)
        settings = client.account_settings() or {}
        self.hold_mode = settings.get("holdMode", "one_way_mode")
        if trading:
            # Writes to the account happen only when ENABLE_TRADING=1; dry-run is read-only.
            if self.hold_mode != "one_way_mode" and not client.positions(category):
                try:
                    client.set_hold_mode("one_way_mode")
                    self.hold_mode = "one_way_mode"
                except BitgetError:
                    pass
            for sym in symbols:
                try:
                    client.set_leverage(category, sym, leverage)
                except BitgetError:
                    pass  # risk gate sizes by notional; leverage only affects margin usage

    def portfolio(self, snap: MarketSnapshot) -> Portfolio:
        assets = self.client.account_assets() or {}
        equity = float(assets.get("accountEquity") or assets.get("usdtEquity") or 0)
        upnl = float(assets.get("unrealisedPnl") or 0)
        positions, foreign = [], []
        for r in self.client.positions(self.category):
            qty = float(r.get("total") or 0)
            if qty == 0:
                continue
            side = r.get("posSide") if r.get("posSide") in ("long", "short") else ("long" if qty > 0 else "short")
            opened = r.get("createdTime")
            p = Position(
                symbol=r["symbol"], side=side, qty=abs(qty),
                avg_price=float(r.get("avgPrice") or 0), mark_price=float(r.get("markPrice") or 0),
                unrealized_pnl=float(r.get("unrealisedPnl") or 0),
                opened_at=iso(datetime.fromtimestamp(int(opened) / 1000, timezone.utc)) if opened else None,
            )
            (positions if p.symbol in self.managed else foreign).append(p)
        return Portfolio("bitget_demo", equity, upnl, positions, foreign)

    def execute(self, intent: dict, client_oid: str, snap: MarketSnapshot, now: datetime, submit: bool) -> dict:
        view = snap.views.get(intent["symbol"])  # a failed fetch this tick must not crash a close
        meta = (view.meta if view else None) or {}
        order = {
            "category": self.category,
            "symbol": intent["symbol"],
            "qty": intent["qty"],
            "side": intent["side"],
            "orderType": "market",
            "clientOid": client_oid,
        }
        if intent["reduce_only"]:
            order["reduceOnly"] = "yes"
        if self.hold_mode == "hedge_mode":
            order["posSide"] = intent["pos_side"]
        if intent.get("stop_loss_price"):
            order["stopLoss"] = fmt_decimal(intent["stop_loss_price"], int(meta.get("pricePrecision") or 2))
            order["slOrderType"] = "market"
        if intent.get("take_profit_price"):
            order["takeProfit"] = fmt_decimal(intent["take_profit_price"], int(meta.get("pricePrecision") or 2))
            order["tpOrderType"] = "market"
        if not (submit and self.trading):
            return {"status": "would_submit", "venue": "bitget_demo", "client_oid": client_oid, "order": order}

        attempts = []
        placed = None
        for attempt in (1, 2):
            try:
                placed = self.client.place_order(order)
                attempts.append({"attempt": attempt, "ok": True})
                break
            except BitgetError as e:
                attempts.append({"attempt": attempt, "ok": False, "error": str(e), "code": e.code})
                ambiguous = e.code in AMBIGUOUS_ORDER_CODES or e.http_status is None or (e.http_status or 0) >= 500
                if not ambiguous:
                    return {"status": "rejected", "venue": "bitget_demo", "client_oid": client_oid,
                            "order": order, "attempts": attempts}
                # Outcome unknown: look the order up by clientOid before any resubmission.
                time.sleep(1.0)
                found = self.client.order_info(client_oid)
                if found:
                    placed = found
                    attempts.append({"attempt": attempt, "recovered_by_client_oid": True})
                    break
        if placed is None:
            return {"status": "unknown", "venue": "bitget_demo", "client_oid": client_oid,
                    "order": order, "attempts": attempts}

        info = None
        for _ in range(6):
            time.sleep(1.0)
            try:
                info = self.client.order_info(client_oid)
            except BitgetError:
                continue
            if info and info.get("orderStatus") in ("filled", "cancelled"):
                break
        info = info or {}
        fee = sum(abs(float(f.get("fee") or 0)) for f in info.get("feeDetail") or [] if isinstance(f, dict))
        return {
            "status": info.get("orderStatus", "submitted"),
            "venue": "bitget_demo",
            "client_oid": client_oid,
            "order_id": (placed or {}).get("orderId") or info.get("orderId"),
            "fill_price": float(info["avgPrice"]) if info.get("avgPrice") else None,
            "qty": float(info["cumExecQty"]) if info.get("cumExecQty") else None,
            "fee": round(fee, 6) if fee else None,
            "order": order,
            "attempts": attempts,
        }

    def detect_closed(self, prev: dict, portfolio: Portfolio) -> list[dict]:
        """Positions present last tick but gone now were closed (by us, the exchange stop, or liquidation)."""
        closed = []
        current = {p.symbol for p in portfolio.positions}
        for sym, p in prev.items():
            if sym in current or sym not in self.managed:  # a foreign close is not our trade, win or lose
                continue
            pnl, source = None, "position_history"
            try:
                hist = self.client.position_history(self.category, sym, limit=1)
                if hist:
                    pnl = float(hist[0].get("netProfit") or hist[0].get("cumRealisedPnl") or 0)
            except BitgetError as e:
                source = f"unavailable: {e}"
            closed.append({"symbol": sym, "side": p.get("side"), "pnl": pnl, "pnl_source": source})
        return closed
