"""A per-UTC-day ceiling on model calls, so a fixed credit lasts a known number of days.

The cap is deliberately crude: it counts calls (and cost, where the provider reports it) and
refuses new ones once the day's allowance is gone. Ticks still run and are still logged; they
simply record that the model was not consulted, which keeps the log honest about the gap.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _day(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def roll(budget: dict, now: datetime) -> dict:
    """Reset the counters when the UTC day turns. Mutates and returns the same dict."""
    if budget.get("day") != _day(now):
        budget.update(day=_day(now), calls=0, cost_usd=0.0)
    budget.setdefault("calls", 0)
    budget.setdefault("cost_usd", 0.0)
    return budget


def exhausted(budget: dict, limits: dict) -> str | None:
    """The reason the day's allowance is gone, or None while calls are still allowed."""
    max_calls = limits.get("max_calls_per_day")
    if max_calls and budget["calls"] >= max_calls:
        return f"{budget['calls']} model calls today (cap {max_calls})"
    max_cost = limits.get("max_cost_usd_per_day")
    if max_cost and budget["cost_usd"] >= max_cost:
        return f"${budget['cost_usd']:.4f} spent today (cap ${max_cost})"
    return None


def record(budget: dict, cost_usd: float | None) -> dict:
    budget["calls"] = budget.get("calls", 0) + 1
    budget["cost_usd"] = round(budget.get("cost_usd", 0.0) + (cost_usd or 0.0), 6)
    return budget
