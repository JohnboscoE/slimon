"""CLI.

  python -m slimon check [--llm]   verify venue access, demo instruments, key permissions
  python -m slimon once            run a single tick now and print the record
  python -m slimon run             run the loop (one tick per closed 5m candle)
  python -m slimon report          rebuild reports/paper_trades.csv and the headline numbers from the log
"""

from __future__ import annotations

import json
import sys

from .bitget import BitgetClient, BitgetError
from .config import load_config


def _ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def check(with_llm: bool) -> int:
    cfg = load_config()
    a = cfg.agent
    bad = 0
    print(f"mode={cfg.mode}  config_hash={cfg.config_hash}  ENABLE_TRADING={'1' if cfg.enable_trading else '0'}")

    print("\nPublic market data")
    pub = BitgetClient()
    try:
        demo = {r["symbol"]: r for r in pub.instruments(a["category"], venue="demo")}
        stocks = sorted(s for s, r in demo.items() if r.get("symbolType") == "stock")
        _ok(f"demo venue lists {len(stocks)} US-stock perps: {', '.join(stocks)}")
        for s in a["whitelist"]:
            st = demo.get(s, {}).get("status")
            (_ok if st == "online" else _fail)(f"whitelist {s}: demo status={st}")
            bad += st != "online"
        live = {t["symbol"] for t in pub.tickers(a["category"], venue="live")}
        missing = [s for s in a["watchlist"] if s not in live]
        (_fail if missing else _ok)(f"live tickers for watchlist" + (f" missing {missing}" if missing else ""))
        bad += bool(missing)
    except BitgetError as e:
        _fail(f"public API: {e}")
        bad += 1

    print("\nBitget demo key")
    s = cfg.secrets
    if not s.has_bitget:
        _warn("no Bitget credentials in .env -> running in 'sim' mode (local paper book)")
    else:
        c = BitgetClient(s.bitget_key, s.bitget_secret, s.bitget_passphrase)
        try:
            info = c.account_info() or {}
            _ok(f"signed call with paptrading:1 succeeded (uid {str(info.get('userId', ''))[:3]}***)")
            perms = info.get("permissions") or []
            print(f"         permType={info.get('permType')} permissions={perms}")
            if "withdraw" in perms:
                _fail("key has WITHDRAW permission - the agent will refuse to run. Recreate the key without it.")
                bad += 1
            if not perms:
                _warn("the demo API does not report key permissions - confirm in the Bitget UI: "
                      "read/write trade, NO withdraw")
            elif info.get("permType") != "read-and-write" or "uta_trade" not in perms:
                _warn("key is not read-and-write with uta_trade; orders will be rejected")
            (_ok if info.get("ips") else _warn)("IP binding " + ("present" if info.get("ips") else "NOT set - bind the key to this machine's IP"))
            st = c.account_settings() or {}
            _ok(f"accountMode={st.get('accountMode')} holdMode={st.get('holdMode')}")
            assets = c.account_assets() or {}
            equity = float(assets.get("accountEquity") or 0)
            if equity > 0:
                _ok(f"demo equity={equity} unrealisedPnl={assets.get('unrealisedPnl')}")
            else:
                _fail("demo unified account has 0 equity - claim demo funds in the Bitget app (Demo mode)")
                bad += 1
            _ok(f"open positions: {len([p for p in c.positions(a['category']) if float(p.get('total') or 0)])}")
        except BitgetError as e:
            _fail(f"signed demo call failed: {e}")
            print("         (demo keys need the `paptrading: 1` header - sent automatically; check key/secret/passphrase)")
            bad += 1

    llm = cfg.llm
    print(f"\nLLM ({llm['provider']}: {llm['model']})")
    if not s.llm_key(llm["provider"]):
        key_var = "QWEN_API_KEY" if llm["provider"] == "qwen" else "ANTHROPIC_API_KEY"
        _fail(f"{key_var} not set - ticks with events will log an llm error and take no action")
        bad += 1
    elif with_llm:
        # A real decision on a quiet synthetic tick: exercises the prompt, schema and validation end to end.
        from .decision import DecisionMaker
        res = DecisionMaker.from_config(cfg).decide({"now_utc": "check", "us_session": "closed", "events": [],
                                                     "portfolio": {"positions": []}, "note": "connectivity check"})
        if res["decision"]:
            _ok(f"{res.get('served_by')} returned a valid decision ({res['decision']['action']}) "
                f"in {res.get('latency_ms')} ms, request {res.get('request_id')}")
        else:
            _fail(f"{llm['provider']}: {res['error']}")
            bad += 1
    else:
        _ok(f"{llm['provider']} API key present (use --llm to make a test call)")

    print("\n" + ("all checks passed" if not bad else f"{bad} check(s) failed"))
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd == "check":
        return check("--llm" in argv)
    if cmd == "report":
        from .report import main as report_main
        return report_main()
    if cmd in ("once", "run"):
        from .agent import Agent, _one_line
        agent = Agent(load_config())
        if cmd == "once":
            rec = agent.tick()
            print(json.dumps(rec, indent=2, default=str))
            print(_one_line(rec))
            return 0
        print(f"slimon running in {agent.cfg.mode} mode; Ctrl+C to stop", flush=True)
        try:
            agent.run_forever()
        except KeyboardInterrupt:
            print("stopped")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
