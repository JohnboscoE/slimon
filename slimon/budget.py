"""A per-UTC-day ceiling on model calls, so a fixed credit lasts a known number of days.

The allowance is split by session. A single flat cap looked prudent and behaved badly: with a
position held overnight, every tick carrying any event called the model, and on 23-25 September the
whole day's budget was gone before 06:00 UTC, so the entire US session ran without a single
decision. The quiet hours now have their own small allowance and cannot spend the session's.

The cap is deliberately crude: it counts calls (and cost, where the provider reports it) and
refuses new ones once the allowance is gone. Ticks still run and are still logged; they simply
record that the model was not consulted, which keeps the log honest about the gap.
"""

from __future__ import annotations

from datetime import datetime, timezone

# US pre-market, regular and after-hours: the sessions in which a position can be opened.
OPEN_SESSIONS = ("pre", "regular", "post")


def _day(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _bucket(session: str) -> str:
    return "calls" if session in OPEN_SESSIONS else "calls_closed"


def roll(budget: dict, now: datetime) -> dict:
    """Reset the counters when the UTC day turns. Mutates and returns the same dict."""
    if budget.get("day") != _day(now):
        budget.update(day=_day(now), calls=0, calls_closed=0, cost_usd=0.0)
    budget.setdefault("calls", 0)
    budget.setdefault("calls_closed", 0)
    budget.setdefault("cost_usd", 0.0)
    return budget


def exhausted(budget: dict, limits: dict, session: str) -> str | None:
    """The reason this session's allowance is gone, or None while calls are still allowed."""
    if _bucket(session) == "calls_closed":
        cap = limits.get("max_calls_per_day_closed")
        if cap and budget["calls_closed"] >= cap:
            return f"{budget['calls_closed']} model calls with the market shut today (cap {cap})"
    else:
        cap = limits.get("max_calls_per_day")
        if cap and budget["calls"] >= cap:
            return f"{budget['calls']} model calls in open sessions today (cap {cap})"
    max_cost = limits.get("max_cost_usd_per_day")
    if max_cost and budget["cost_usd"] >= max_cost:
        return f"${budget['cost_usd']:.4f} spent today (cap ${max_cost})"
    return None


def record(budget: dict, cost_usd: float | None, session: str) -> dict:
    key = _bucket(session)
    budget[key] = budget.get(key, 0) + 1
    budget["cost_usd"] = round(budget.get("cost_usd", 0.0) + (cost_usd or 0.0), 6)
    return budget
