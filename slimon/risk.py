"""Deterministic risk layer. Plain code, no model involvement.

The LLM proposes; this module disposes. `evaluate` runs every applicable check and returns
all of them (passed or not), so every verdict in the log shows exactly which rules were
applied and why a proposal was allowed or refused. Risk-reducing actions (CLOSE) are never
blocked by the kill switch, the drawdown breaker, cooldowns or session rules.

`forced_actions` is the other direction: closes the gate initiates on its own (hard stop,
max holding time) regardless of what the model thinks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .broker import Portfolio, Position, floor_to_step, fmt_decimal
from .journal import iso
from .market import MarketSnapshot, SymbolView


def _parse(ts: str | None) -> datetime | None:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# ---------------------------------------------------------------------------
# Mutable risk state (drawdown breaker, loss cooldown, trade counters)
# ---------------------------------------------------------------------------


class RiskBook:
    def __init__(self, data: dict, limits: dict):
        self.d = data
        self.limits = limits
        self.d.setdefault("consecutive_losses", 0)
        self.d.setdefault("last_trade_at", {})

    def roll_day(self, now: datetime, equity: float) -> None:
        today = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if self.d.get("day") != today:
            self.d.update(day=today, day_start_equity=equity, trades_today=0, halted_until=None, halt_reason=None)

    def drawdown_pct(self, equity: float) -> float:
        start = self.d.get("day_start_equity") or equity
        return (equity / start - 1) * 100 if start else 0.0

    def update_breaker(self, now: datetime, equity: float) -> dict | None:
        """Trip the daily breaker if drawdown breaches the limit. Returns a trip event or None."""
        dd = self.drawdown_pct(equity)
        if dd <= -self.limits["daily_drawdown_halt_pct"] and not self.halted(now):
            midnight = (now.astimezone(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            self.d["halted_until"] = iso(midnight)
            self.d["halt_reason"] = f"daily drawdown {dd:.2f}% <= -{self.limits['daily_drawdown_halt_pct']}%"
            return {"type": "drawdown_breaker_tripped", "drawdown_pct": round(dd, 3), "halted_until": iso(midnight)}
        return None

    def halted(self, now: datetime) -> bool:
        until = _parse(self.d.get("halted_until"))
        return bool(until and now < until)

    def in_cooldown(self, now: datetime) -> bool:
        until = _parse(self.d.get("cooldown_until"))
        return bool(until and now < until)

    def record_closed(self, closed: list[dict], now: datetime) -> list[dict]:
        notes = []
        for t in closed:
            if t.get("pnl") is None:
                continue
            if t["pnl"] < 0:
                self.d["consecutive_losses"] += 1
            else:
                self.d["consecutive_losses"] = 0
            if self.d["consecutive_losses"] >= self.limits["consecutive_loss_limit"]:
                until = now + timedelta(minutes=self.limits["loss_cooldown_minutes"])
                self.d["cooldown_until"] = iso(until)
                notes.append({"type": "loss_cooldown_started", "consecutive_losses": self.d["consecutive_losses"],
                              "cooldown_until": iso(until)})
                self.d["consecutive_losses"] = 0
        return notes

    def record_trade(self, symbol: str, now: datetime) -> None:
        self.d["trades_today"] = self.d.get("trades_today", 0) + 1
        self.d["last_trade_at"][symbol] = iso(now)

    def snapshot(self, now: datetime, equity: float) -> dict:
        return {
            "day": self.d.get("day"),
            "day_start_equity": self.d.get("day_start_equity"),
            "drawdown_pct": round(self.drawdown_pct(equity), 3),
            "halted": self.halted(now),
            "halted_until": self.d.get("halted_until"),
            "consecutive_losses": self.d.get("consecutive_losses", 0),
            "in_cooldown": self.in_cooldown(now),
            "cooldown_until": self.d.get("cooldown_until"),
            "trades_today": self.d.get("trades_today", 0),
        }


# ---------------------------------------------------------------------------
# Pure evaluation
# ---------------------------------------------------------------------------


@dataclass
class RiskContext:
    now: datetime
    session: str
    portfolio: Portfolio
    snap: MarketSnapshot
    whitelist: list[str]
    limits: dict
    book: RiskBook
    kill_switch: bool
    event_ids: set[str] = field(default_factory=set)


class _Checks:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, name: str, passed: bool, detail: str) -> bool:
        self.items.append({"check": name, "passed": bool(passed), "detail": detail})
        return passed

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.items if not c["passed"]]


def _qty_step(meta: dict) -> float:
    try:
        step = float(meta.get("quantityMultiplier") or 0)
    except (TypeError, ValueError):
        step = 0.0
    if step <= 0:
        step = 10 ** -int(meta.get("quantityPrecision") or 2)
    return step


def _close_intent(pos: Position, view: SymbolView | None, reason: str) -> dict:
    meta = (view.meta if view else None) or {}
    return {
        "action": "CLOSE",
        "symbol": pos.symbol,
        "side": "sell" if pos.side == "long" else "buy",
        "pos_side": pos.side,
        "qty": fmt_decimal(pos.qty, int(meta.get("quantityPrecision") or 4)),
        "reduce_only": True,
        "ref_price": view.demo_price if view else pos.mark_price,
        "reason": reason,
    }


def evaluate(decision: dict, ctx: RiskContext) -> dict:
    """Return {"verdict": PASS|VETO|NO_ACTION, "checks": [...], "veto_reasons": [...], "intent": {...}|None}."""
    c = _Checks()
    L = ctx.limits
    action = decision.get("action")
    sym = (decision.get("instrument") or "").strip().upper()
    conf = decision.get("confidence")
    notional = decision.get("notional_usdt")

    # --- structural sanity on model output (applies to every action) ---
    c.add("schema.action", action in ("OPEN_LONG", "OPEN_SHORT", "CLOSE", "NO_TRADE"), f"action={action!r}")
    c.add("schema.confidence_range", _finite(conf) and 0 <= conf <= 1, f"confidence={conf!r}")
    ids = decision.get("triggering_event_ids") or []
    unknown = [i for i in ids if i not in ctx.event_ids]
    c.add("schema.event_ids_grounded", bool(ids) and not unknown,
          "all cited event IDs were provided this tick" if ids and not unknown
          else f"cited={ids} unknown={unknown}")

    if action == "NO_TRADE":
        return _result(c, "NO_ACTION", None)

    view = ctx.snap.views.get(sym)
    pos = ctx.portfolio.position(sym)

    if action == "CLOSE":
        c.add("close.position_exists", pos is not None,
              f"{sym} {pos.side} qty={pos.qty}" if pos else f"no open position in {sym!r}")
        if c.failed:
            return _result(c, "VETO", None)
        return _result(c, "PASS", _close_intent(pos, view, "model_decision"))

    # --- OPEN_LONG / OPEN_SHORT ---
    side = "long" if action == "OPEN_LONG" else "short"
    equity = ctx.portfolio.equity
    c.add("schema.notional_sane", _finite(notional) and notional > 0, f"notional_usdt={notional!r}")
    notional = float(notional) if _finite(notional) else 0.0

    c.add("kill_switch", not ctx.kill_switch, "STOP file present - operator halt" if ctx.kill_switch else "not engaged")
    c.add("whitelist", sym in ctx.whitelist, f"{sym!r} {'is' if sym in ctx.whitelist else 'is NOT'} on the trading whitelist")
    status = ((view.meta if view else None) or {}).get("status")
    c.add("instrument_online", status == "online", f"demo instrument status={status!r}")
    c.add("session_open", ctx.session in L["open_sessions"],
          f"US session={ctx.session!r}; new positions allowed in {L['open_sessions']}")

    dd = ctx.book.drawdown_pct(equity)
    halted = ctx.book.halted(ctx.now)
    c.add("daily_drawdown_breaker", not halted and dd > -L["daily_drawdown_halt_pct"],
          f"drawdown {dd:+.2f}% vs limit -{L['daily_drawdown_halt_pct']}%"
          + (f"; halted until {ctx.book.d.get('halted_until')}" if halted else ""))
    c.add("loss_cooldown", not ctx.book.in_cooldown(ctx.now),
          f"cooldown until {ctx.book.d.get('cooldown_until')}" if ctx.book.in_cooldown(ctx.now)
          else f"{ctx.book.d.get('consecutive_losses', 0)} consecutive losses (limit {L['consecutive_loss_limit']})")
    c.add("min_confidence", _finite(conf) and conf >= L["min_confidence"],
          f"confidence {conf} vs minimum {L['min_confidence']}")
    trades = ctx.book.d.get("trades_today", 0)
    c.add("max_trades_per_day", trades < L["max_trades_per_day"], f"{trades} trades today (max {L['max_trades_per_day']})")
    last = _parse(ctx.book.d.get("last_trade_at", {}).get(sym))
    gap_ok = last is None or ctx.now - last >= timedelta(minutes=L["symbol_min_minutes_between_trades"])
    c.add("symbol_trade_spacing", gap_ok,
          "no recent trade" if last is None else
          f"last {sym} trade {(ctx.now - last).total_seconds() / 60:.0f}m ago (min {L['symbol_min_minutes_between_trades']}m)")

    c.add("direction_conflict", pos is None or pos.side == side,
          f"existing {pos.side} position; CLOSE before reversing" if pos and pos.side != side else "no conflicting position")

    c.add("max_order_notional", notional <= L["max_order_notional_usdt"],
          f"{notional:.2f} vs cap {L['max_order_notional_usdt']} USDT")
    existing = pos.notional if pos and pos.side == side else 0.0
    pos_cap = equity * L["max_position_pct_equity"] / 100
    c.add("position_cap", existing + notional <= pos_cap,
          f"position would be {existing + notional:.2f} vs {L['max_position_pct_equity']}% of equity = {pos_cap:.2f}")
    gross_cap = equity * L["max_gross_exposure_pct_equity"] / 100
    gross = ctx.portfolio.gross_exposure + notional
    c.add("gross_exposure_cap", gross <= gross_cap,
          f"gross exposure would be {gross:.2f} vs {L['max_gross_exposure_pct_equity']}% of equity = {gross_cap:.2f}")
    n_open = len(ctx.portfolio.positions)
    c.add("max_open_positions", pos is not None or n_open < L["max_open_positions"],
          f"{n_open} open (max {L['max_open_positions']})")

    price = view.demo_price if view else None
    c.add("price_available", bool(price), f"demo price={price}")
    spread = view.demo_spread_pct if view else None
    c.add("spread_sanity", spread is not None and spread <= L["max_spread_pct"],
          f"demo spread {spread if spread is None else round(spread, 4)}% vs max {L['max_spread_pct']}%")
    div = view.divergence_pct if view else None
    c.add("venue_divergence", div is not None and abs(div) <= L["max_live_demo_divergence_pct"],
          f"demo vs live {div if div is None else round(div, 3)}% vs max ±{L['max_live_demo_divergence_pct']}%")

    intent = None
    if price and view and view.meta:
        meta = view.meta
        step = _qty_step(meta)
        qty = floor_to_step(notional / price, step)
        min_qty = float(meta.get("minOrderQty") or 0)
        min_amt = float(meta.get("minOrderAmount") or 0)
        ok = qty > 0 and qty >= min_qty and qty * price >= min_amt
        c.add("min_order_size", ok, f"qty {qty} (step {step}, min {min_qty}); value {qty * price:.2f} (min {min_amt})")
        sl = L["stop_loss_pct"] / 100
        stop = price * (1 - sl) if side == "long" else price * (1 + sl)
        intent = {
            "action": action,
            "symbol": sym,
            "side": "buy" if side == "long" else "sell",
            "pos_side": side,
            "qty": fmt_decimal(qty, int(meta.get("quantityPrecision") or 4)),
            "reduce_only": False,
            "ref_price": price,
            "notional_usdt": round(qty * price, 4),
            "stop_loss_price": round(stop, int(meta.get("pricePrecision") or 2)),
        }
    else:
        c.add("min_order_size", False, "cannot size order without demo price and instrument metadata")

    if c.failed:
        return _result(c, "VETO", None)
    return _result(c, "PASS", intent)


def _result(c: _Checks, verdict: str, intent: dict | None) -> dict:
    return {
        "verdict": verdict,
        "veto_reasons": [f"{f['check']}: {f['detail']}" for f in c.failed] if verdict == "VETO" else [],
        "checks": c.items,
        "intent": intent,
    }


def forced_actions(ctx: RiskContext) -> list[dict]:
    """Closes the risk layer initiates by itself. These bypass the model entirely."""
    out = []
    L = ctx.limits
    for p in ctx.portfolio.positions:
        view = ctx.snap.views.get(p.symbol)
        if p.pnl_pct <= -L["stop_loss_pct"]:
            out.append({"rule": "hard_stop", "detail": f"{p.symbol} {p.side} at {p.pnl_pct:+.2f}% <= -{L['stop_loss_pct']}%",
                        "intent": _close_intent(p, view, "hard_stop")})
            continue
        opened = _parse(p.opened_at)
        if opened and ctx.now - opened >= timedelta(hours=L["max_holding_hours"]):
            out.append({"rule": "max_holding_time",
                        "detail": f"{p.symbol} held {(ctx.now - opened).total_seconds() / 3600:.1f}h >= {L['max_holding_hours']}h",
                        "intent": _close_intent(p, view, "max_holding_time")})
    return out
