"""Tick orchestration: perceive -> decide -> gate -> execute -> journal. One log record per tick."""

from __future__ import annotations

import subprocess
import time
import traceback
from datetime import datetime

from . import gitsync
from .bitget import BitgetClient, BitgetError
from .broker import BitgetBroker, SimBroker
from .config import KILL_SWITCH_PATH, ROOT, Config
from .decision import DecisionMaker
from .journal import Journal, State, iso, utcnow
from .market import Market, us_session
from .perception import Perception
from .risk import RiskBook, RiskContext, evaluate, forced_actions

SCHEMA = "slimon.tick/v1"
RECENT_N = 8
FILLED_LIKE = {"filled", "partially_filled", "submitted", "new", "live", "would_submit"}


def _git_head() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def worth_a_decision(events: list[dict], whitelist: list[str], holding: bool) -> bool:
    """Spend a model call only when the answer could lead somewhere: an event on a tradable symbol,
    a session edge or position review, or any event at all while positions are held. Events on
    watch-only symbols alone can only ever produce NO_TRADE, so they are logged but not sent."""
    if holding:
        return bool(events)
    return any(e.get("symbol") is None or e.get("symbol") in whitelist or e.get("type") == "position_review"
               for e in events)


def _for_model(ev: dict) -> dict:
    """Session events carry the whole cross-section, which the model already gets under "market".
    Send it once; the event log keeps the full payload."""
    payload = ev.get("payload") or {}
    if "cross_section" not in payload:
        return ev
    return {**ev, "payload": {k: v for k, v in payload.items() if k != "cross_section"}}


class Agent:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        s = cfg.secrets
        self.client = BitgetClient(s.bitget_key, s.bitget_secret, s.bitget_passphrase)
        a, p = cfg.agent, cfg.perception
        self.market = Market(self.client, a["category"], p["candle_interval"], p["lookback_candles"])
        self.state = State()
        self.journal = Journal(s.values())
        self.perception = Perception(p, self.state)
        self.dm = DecisionMaker.from_config(cfg)
        self.book = RiskBook(self.state.get("risk", {}), cfg.risk)
        startup = {"type": "startup", "ts": iso(utcnow()), "mode": cfg.mode, "config_hash": cfg.config_hash,
                   "git_head": _git_head(), "llm_provider": self.dm.provider, "model": self.dm.model,
                   "llm_configured": bool(self.dm.api_key)}
        if cfg.mode == "sim":
            self.broker = SimBroker(cfg.sim["starting_equity_usdt"], cfg.sim["taker_fee_rate"])
        else:
            info = self.client.account_info() or {}
            perms = info.get("permissions") or []
            startup["key_check"] = {"perm_type": info.get("permType"), "permissions": perms,
                                    "permissions_reported": bool(perms), "ip_bound": bool(info.get("ips"))}
            if "withdraw" in perms:
                self.journal.run({**startup, "fatal": "API key has withdraw permission; refusing to run"}, utcnow())
                raise SystemExit("Refusing to run: the Bitget key has WITHDRAW permission. Create a key without it.")
            self.broker = BitgetBroker(self.client, a["category"], trading=cfg.enable_trading,
                                       leverage=cfg.risk["leverage"], symbols=a["whitelist"])
            startup["hold_mode"] = self.broker.hold_mode
        self.journal.run(startup, utcnow())
        self.state.save()

    # ------------------------------------------------------------------

    def _context(self, now, session, events, snap, portfolio) -> dict:
        a = self.cfg.agent
        return {
            "now_utc": iso(now),
            "us_session": session,
            "events": [_for_model(e) for e in events],
            "market": [snap.views[s].summary() for s in a["watchlist"] if s in snap.views],
            "portfolio": portfolio.to_dict(),
            "tradable_whitelist": a["whitelist"],
            "risk_limits": self.cfg.risk,
            "risk_state": self.book.snapshot(now, portfolio.equity),
            "recent_decisions": self.state.get("recent_decisions", []),
            "recent_closed_trades": self.state.get("recent_closed", []),
        }

    def tick(self, now: datetime | None = None) -> dict:
        now = now or utcnow()
        tick_id = now.strftime("%Y%m%dT%H%M%S")
        session = us_session(now)
        a = self.cfg.agent
        rec: dict = {"schema": SCHEMA, "tick_id": tick_id, "ts": iso(now), "mode": self.cfg.mode,
                     "config_hash": self.cfg.config_hash, "session": session, "errors": []}

        snap = self.market.snapshot(a["watchlist"], now)
        rec["errors"] += snap.errors
        try:
            portfolio = self.broker.portfolio(snap)
        except BitgetError as e:
            rec["errors"].append(f"portfolio: {e}")
            rec.update(events=[], llm={"called": False, "reason": "portfolio_unavailable"}, decision=None,
                       risk=None, execution=None)
            self.journal.tick(rec, now)
            return rec
        rec["portfolio"] = portfolio.to_dict()

        # Bookkeeping from the previous tick: closed trades feed the loss cooldown.
        closed = self.broker.detect_closed(self.state.get("positions_last_tick", {}), portfolio)
        notes = self.book.record_closed(closed, now)
        self.book.roll_day(now, portfolio.equity)
        trip = self.book.update_breaker(now, portfolio.equity)
        rec["closed_trades"] = closed
        rec["risk_notes"] = notes + ([trip] if trip else [])
        recent_closed = self.state.get("recent_closed", [])
        recent_closed.extend({**t, "detected_at": iso(now)} for t in closed)
        del recent_closed[:-RECENT_N]

        ctx = RiskContext(now=now, session=session, portfolio=portfolio, snap=snap, whitelist=a["whitelist"],
                          limits=self.cfg.risk, book=self.book, kill_switch=KILL_SWITCH_PATH.exists())

        # Risk-initiated closes run before the model is consulted.
        rec["forced_actions"] = []
        for i, f in enumerate(forced_actions(ctx)):
            f["execution"] = self.broker.execute(f["intent"], f"slm{tick_id}f{i}", snap, now, submit=True)
            rec["forced_actions"].append(f)
        if rec["forced_actions"]:
            portfolio = self.broker.portfolio(snap)
            ctx.portfolio = portfolio

        events = self.perception.detect(snap, portfolio, now, session)
        for ev in events:
            self.journal.event(ev, now)
        rec["events"] = events
        ctx.event_ids = {e["id"] for e in events}

        decision = None
        if not events:
            rec["llm"] = {"called": False, "reason": "no_events"}
        elif session == "closed" and not portfolio.positions:
            rec["llm"] = {"called": False, "reason": "us_market_closed_and_flat"}
        elif not worth_a_decision(events, a["whitelist"], holding=bool(portfolio.positions)):
            rec["llm"] = {"called": False, "reason": "no_tradable_events"}
        else:
            llm = self.dm.decide(self._context(now, session, events, snap, portfolio))
            decision = llm.pop("decision")
            rec["llm"] = llm
            if llm.get("error"):
                rec["errors"].append(f"llm: {llm['error']}")
        rec["decision"] = decision

        rec["risk"] = None
        rec["execution"] = None
        if decision:
            verdict = evaluate(decision, ctx)
            rec["risk"] = verdict
            if verdict["verdict"] == "PASS":
                ex = self.broker.execute(verdict["intent"], f"slm{tick_id}d", snap, now, submit=True)
                rec["execution"] = ex
                if ex.get("status") in FILLED_LIKE and verdict["intent"]["action"] != "CLOSE":
                    self.book.record_trade(verdict["intent"]["symbol"], now)
            recent = self.state.get("recent_decisions", [])
            recent.append({"tick_id": tick_id, "action": decision["action"], "instrument": decision["instrument"],
                           "confidence": decision["confidence"], "verdict": verdict["verdict"],
                           "veto_reasons": verdict["veto_reasons"],
                           "execution_status": (rec["execution"] or {}).get("status")})
            del recent[:-RECENT_N]

        try:
            after = self.broker.portfolio(snap) if (rec["execution"] or rec["forced_actions"]) else portfolio
        except BitgetError as e:
            rec["errors"].append(f"portfolio_after: {e}")
            after = portfolio
        rec["portfolio_after"] = after.to_dict() if after is not portfolio else None
        rec["risk_state"] = self.book.snapshot(now, after.equity)
        self.state.data["positions_last_tick"] = {p.symbol: {"side": p.side, "qty": p.qty} for p in after.positions}
        self.state.data["risk"] = self.book.d
        self.state.save()
        self.journal.tick(rec, now)
        return rec

    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        step = self.cfg.agent["tick_seconds"]
        while True:
            now = time.time()
            nxt = (int(now // step) + 1) * step + 15  # 15s after the candle boundary so it has closed
            time.sleep(max(0.0, nxt - now))
            when = utcnow()
            try:
                rec = self.tick(when)
                print(_one_line(rec), flush=True)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # a failed tick is still a logged tick
                err = {"schema": SCHEMA, "tick_id": when.strftime("%Y%m%dT%H%M%S"), "ts": iso(when),
                       "mode": self.cfg.mode, "config_hash": self.cfg.config_hash, "session": us_session(when),
                       "errors": [f"tick_crashed: {type(e).__name__}: {e}"],
                       "traceback": traceback.format_exc(limit=5)}
                self.journal.tick(err, when)
                print(f"[{iso(when)}] tick crashed: {type(e).__name__}: {e}", flush=True)
            gitsync.maybe_commit(self.cfg, self.state, utcnow())


def _one_line(rec: dict) -> str:
    d = rec.get("decision") or {}
    r = rec.get("risk") or {}
    ex = rec.get("execution") or {}
    parts = [f"[{rec['ts']}] {rec['mode']} {rec['session']}", f"events={len(rec.get('events', []))}"]
    if rec.get("llm", {}).get("called"):
        parts.append(f"decision={d.get('action')} {d.get('instrument') or ''}".rstrip())
        if r:
            parts.append(f"gate={r['verdict']}")
            if r["veto_reasons"]:
                parts.append("veto: " + "; ".join(r["veto_reasons"]))
        if ex:
            parts.append(f"exec={ex.get('status')}")
    else:
        parts.append(f"llm=skip({rec.get('llm', {}).get('reason')})")
    if rec.get("forced_actions"):
        parts.append(f"forced={[f['rule'] for f in rec['forced_actions']]}")
    if rec.get("errors"):
        parts.append(f"errors={rec['errors']}")
    return " | ".join(parts)
