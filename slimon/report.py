"""Paper-trading report: a flat record of every order that reached the venue, and the headline
numbers, rebuilt from the decision log alone.

  python -m slimon report      writes reports/paper_trades.csv and prints the summary

Nothing here is hand-entered: every row and figure is derived from logs/decisions/*.jsonl, so
anyone with the repository can regenerate it and check it against the raw records.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .config import LOG_DIR, ROOT

FIELDS = ["timestamp_utc", "tick_id", "instrument", "action", "direction", "position_side", "price",
          "quantity", "notional_usdt", "fee_usdt", "status", "client_oid", "decided_by", "reason",
          "equity_before_usdt", "equity_after_usdt", "balance_change_usdt"]

# Statuses where the order was actually filled on the venue (not merely would-submit or rejected).
FILLED = {"filled", "partially_filled"}


def _rows() -> list[dict]:
    rows = []
    for f in sorted((LOG_DIR / "decisions").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # a torn final line from a run that was cut off mid-write
    rows.sort(key=lambda r: r.get("ts", ""))
    return rows


def _equity(portfolio: dict | None) -> float | None:
    return (portfolio or {}).get("equity")


def fills(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        before = _equity(r.get("portfolio"))
        after = _equity(r.get("portfolio_after")) or before
        sent = []
        for f in r.get("forced_actions") or []:
            sent.append((f.get("intent") or {}, f.get("execution") or {}, "risk_gate", f.get("rule")))
        ex = r.get("execution")
        if ex:
            d = r.get("decision") or {}
            sent.append(((r.get("risk") or {}).get("intent") or {}, ex, "model", d.get("reasoning", "")[:200]))
        for intent, ex, who, reason in sent:
            order = ex.get("order") or {}
            price, qty = ex.get("fill_price"), ex.get("qty")
            out.append({
                "timestamp_utc": r.get("ts"), "tick_id": r.get("tick_id"),
                "instrument": order.get("symbol") or intent.get("symbol"),
                "action": intent.get("action"), "direction": order.get("side") or intent.get("side"),
                "position_side": intent.get("pos_side"), "price": price, "quantity": qty,
                "notional_usdt": round(price * qty, 4) if price and qty else None,
                "fee_usdt": ex.get("fee"), "status": ex.get("status"), "client_oid": ex.get("client_oid"),
                "decided_by": who, "reason": reason,
                "equity_before_usdt": before, "equity_after_usdt": after,
                "balance_change_usdt": round(after - before, 4) if before is not None and after is not None else None,
            })
    return out


def round_trips(trades: list[dict]) -> list[dict]:
    """Pair each filled open with the next filled close of the same instrument."""
    open_by_symbol: dict[str, dict] = {}
    out = []
    for t in trades:
        if t["status"] not in FILLED or not t["price"] or not t["quantity"]:
            continue
        if t["action"] in ("OPEN_LONG", "OPEN_SHORT"):
            open_by_symbol[t["instrument"]] = t
        elif t["action"] == "CLOSE" and t["instrument"] in open_by_symbol:
            o = open_by_symbol.pop(t["instrument"])
            sign = 1 if o["position_side"] == "long" else -1
            qty = min(o["quantity"], t["quantity"])
            gross = (t["price"] - o["price"]) * qty * sign
            fees = (o["fee_usdt"] or 0) + (t["fee_usdt"] or 0)
            out.append({"instrument": o["instrument"], "side": o["position_side"], "opened": o["timestamp_utc"],
                        "closed": t["timestamp_utc"], "entry": o["price"], "exit": t["price"], "quantity": qty,
                        "gross_pnl_usdt": round(gross, 4), "fees_usdt": round(fees, 4),
                        "net_pnl_usdt": round(gross - fees, 4), "return_pct": round(gross / (o["price"] * qty) * 100, 3),
                        "closed_by": t["decided_by"]})
    return out


def summary(rows: list[dict]) -> dict:
    trades = fills(rows)
    trips = round_trips(trades)
    dec = [r for r in rows if r.get("decision")]
    verdicts = defaultdict(int)
    for r in dec:
        verdicts[(r.get("risk") or {}).get("verdict")] += 1
    live = [r for r in rows if r.get("mode") == "live_demo"]
    eq = [(r["ts"], _equity(r.get("portfolio"))) for r in live if _equity(r.get("portfolio"))]
    peak, max_dd = None, 0.0
    for _, e in eq:
        peak = e if peak is None else max(peak, e)
        max_dd = min(max_dd, (e / peak - 1) * 100)
    filled = [t for t in trades if t["status"] in FILLED]
    wins = [t for t in trips if t["net_pnl_usdt"] > 0]
    return {
        "log_period": (rows[0]["ts"], rows[-1]["ts"]) if rows else None,
        "live_demo_period": (eq[0][0], eq[-1][0]) if eq else None,
        "ticks": len(rows), "decisions": len(dec), "verdicts": dict(verdicts),
        "orders_filled": len(filled), "round_trips": len(trips), "winning_trips": len(wins),
        "net_pnl_closed_usdt": round(sum(t["net_pnl_usdt"] for t in trips), 4),
        "fees_usdt": round(sum(t["fee_usdt"] or 0 for t in filled), 4),
        "turnover_usdt": round(sum(t["notional_usdt"] or 0 for t in filled), 2),
        "equity_start_live": eq[0][1] if eq else None, "equity_end_live": eq[-1][1] if eq else None,
        "max_drawdown_pct_live": round(max_dd, 4),
        "trips": trips,
    }


def main() -> int:
    rows = _rows()
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    trades = fills(rows)
    with (out_dir / "paper_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(trades)
    s = summary(rows)
    trips = s.pop("trips")
    print(json.dumps(s, indent=1, default=str))
    print("\nround trips:")
    for t in trips:
        print(f"  {t['instrument']:<11} {t['side']:<5} {t['opened'][:16]} -> {t['closed'][:16]}  "
              f"{t['entry']} -> {t['exit']}  net {t['net_pnl_usdt']:+.4f} USDT ({t['return_pct']:+.3f}%)  by {t['closed_by']}")
    print(f"\nwrote {out_dir / 'paper_trades.csv'} ({len(trades)} rows)")
    return 0
