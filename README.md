# Slimon

An event-driven trading agent for **US-stock perpetuals on Bitget** (Bitget AI Base Camp Hackathon S2, Track 2: Agentic Trading, Event-Driven Agent).

The LLM decides (Qwen by default, Claude as a config switch). A **deterministic risk gate**, written as plain code with no model involvement, can veto any decision. Every tick is written to an append-only decision log, including ticks where nothing happened and every veto.

```
live-venue market data ─► perception (events, timestamped on receipt)
                                   │
                                   ▼
                          LLM: one structured decision
                   (OPEN_LONG / OPEN_SHORT / CLOSE / NO_TRADE,
                    size, confidence, reasoning, cited event IDs)
                                   │
                                   ▼
          deterministic risk gate ── VETO (every failed rule logged) ─┐
                                   │ PASS                             │
                                   ▼                                  │
                 execution on Bitget demo (idempotent clientOid)      │
                                   │                                  │
                                   ▼                                  ▼
                 logs/decisions/YYYY-MM-DD.jsonl  (one record per tick)
```

## Why the risk gate is the product

The model proposes and the gate decides. The gate runs **every** applicable rule on each proposal and records each result, not just the first failure. A veto therefore reads like this (a real record from a smoke test):

```
decision=OPEN_LONG MSTRUSDT | gate=VETO |
  whitelist: 'MSTRUSDT' is NOT on the trading whitelist;
  max_order_notional: 5000.00 vs cap 1500 USDT;
  position_cap: position would be 5000.00 vs 15% of equity = 1499.84;
  gross_exposure_cap: gross exposure would be 5999.71 vs 40% of equity = 3999.56
```

| Rule | What it enforces |
|---|---|
| `schema.*` | The output must be structurally sane: finite numbers, confidence in [0,1], and **every cited event ID must be one the agent actually saw this tick** (catches invented justification) |
| `whitelist` | Perception watches 12 stock perps, but trading is limited to 8 |
| `instrument_online` | The demo instrument must be in `online` status |
| `session_open` | No new positions overnight or at weekends (US pre, regular and post sessions only) |
| `daily_drawdown_breaker` | Equity down ≥3% from the start of the UTC day halts new positions until midnight |
| `loss_cooldown` | 3 consecutive losing trades pause new positions for 4h |
| `min_confidence` | Proposals below 0.55 confidence are refused |
| `max_order_notional` / `position_cap` / `gross_exposure_cap` / `max_open_positions` | Size caps, absolute and as a % of equity |
| `max_trades_per_day` / `symbol_trade_spacing` | Turnover limits |
| `direction_conflict` | No flipping a position in one order; the agent must CLOSE first |
| `spread_sanity` / `venue_divergence` | Refuses to trade into a broken demo book or one priced far from the live market |
| `min_order_size` | The order must meet exchange minimums after rounding to the lot step |
| `kill_switch` | A `STOP` file in the repo root halts all new positions |

Closing a position reduces risk, so kill switches, breakers, cooldowns and session rules never block it.

The gate also acts **on its own**: a hard stop at -2.5% (enforced locally and preset on the exchange) and a 72h maximum holding time close positions without consulting the model.

Positions on symbols outside the whitelist, such as a trade opened by hand in the same account, are not the agent's. It never reviews or closes them and never counts their outcome as its own trade, but their exposure still counts against the gross cap and they are recorded under `foreign_positions` in every log record.

All limits live in [`config/agent.toml`](config/agent.toml). Every log record carries the hash of the config it ran under. The gate is covered by unit tests in [`tests/test_risk.py`](tests/test_risk.py).

## Perception

Signals come from Bitget's **live** public market data, which reflects the real market. Orders fill on the **demo** venue, which has its own thinner order book. The log records both prices.

- `price_move`: a 30-minute return of at least 1% on a closed-candle basis
- `range_expansion` / `volume_spike`: a 5m candle measured against a baseline built **only from candles in the same US session**, so the cash open doesn't register as a spike against the thin pre-market
- `us_regular_open` / `us_regular_close`: scheduled session events carrying the full cross-section
- `position_review`: a held position crosses a PnL band, or has gone 4h without review

Every event is written to `logs/events/` with its `received_at` time and the `source_ts` of the candle it came from, which shows decisions were not made in hindsight.

### When the model is called

The decision model is set in `config/agent.toml` under `[llm]`: **Qwen** (`qwen3.8-max`, through Bitget's hackathon gateway, key in `QWEN_API_KEY`) by default, or **Claude** (`claude-sonnet-5` at `medium` effort, `ANTHROPIC_API_KEY`). Both get the same system prompt, the same JSON schema and the same validation; every call logs its provider, the model that served it, token usage and latency (and `cost_usd` for Claude). The model is consulted only when a tick produces an event it could act on: an event on a tradable symbol, a US session open or close, a position review, or any event while a position is held. Quiet ticks and events on watch-only symbols are logged with the reason the model was not called (`no_events`, `no_tradable_events`, `us_market_closed_and_flat`). The context is sent as compact JSON with the market cross-section included once.

### Data sources

Slimon reads **one source**: Bitget's public market API (`/api/v3/market/instruments`, `/tickers`, `/candles`) for the 12 watched perps, read from both the live venue (signals) and the demo venue (execution prices, spread, instrument status). It does **not** read news, X, Truth Social or any other feed. The track allows other sources (its sub-themes include sentiment and earnings agents); keeping to one is a deliberate choice.

- **What that means for news.** A post from a president or a CEO reaches Slimon as the price move it causes, not as text. Racing headlines is a contest against firms with direct feeds, and a post can be misread, parodied or retracted within minutes. A price that has actually traded is the market's own verdict on the news, whoever broke it.
- **How early.** Each tick runs 15 seconds after a 5-minute candle closes, so a move is caught at the first close after it crosses a threshold: never more than about five minutes late. The delay is on the record, not claimed: every event carries `source_ts` and `received_at`, and every model call logs `latency_ms`.
- **How it is verified.** Detectors use closed candles only. Range and volume are compared against a baseline from the same US session. The model gets the full cross-section, so it can tell one stock's news from an index-wide move. The gate refuses to open a position if the demo book's spread exceeds 0.30% or its price diverges from the live venue by more than 1.5%, and it vetoes any decision that cites an event ID the agent did not see that tick.
- **Weekends and overnight.** Stock perps trade around the clock, so news that breaks at the weekend still moves them. Perception keeps running and logging then, and the model is still consulted about held positions, but no new position is opened outside the US pre, regular and post sessions.

## Modes

| Mode | When | Behaviour |
|---|---|---|
| `sim` | no Bitget key | Local paper book priced off the demo venue's bid/ask |
| `dry_run` | key present, `ENABLE_TRADING` unset | Reads the real demo account; orders are logged as `would_submit` and never sent |
| `live_demo` | key present **and** `ENABLE_TRADING=1` | Orders are sent to the Bitget demo venue |

Every signed request carries `paptrading: 1`, and no code path reaches the live trading venue. The agent refuses to start if the key has withdraw permission.

## Run

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows; use .venv/bin/python elsewhere
cp .env.example .env                                         # fill in keys
.venv/Scripts/python -m slimon check --llm                   # venue, instruments, key permissions, LLM
.venv/Scripts/python -m slimon once                          # one tick, prints the record
.venv/Scripts/python -m slimon run                           # loop: one tick per closed 5m candle
.venv/Scripts/python -m unittest discover -s tests           # risk gate tests
```

## Web UI (`web/`)

A landing page that explains the agent, with an animated walk through one tick (perceive, decide, gate, execute, log), and a **Launch App** button that opens a replay of the decision log at `/app`. The replay needs no keys: it reads `logs/decisions/*.jsonl` straight from the repository, opens on the veto cases, and expands any tick into the events seen, the model's reasoning and invalidation, every gate check with its detail, and the execution result.

Next.js 16, TypeScript, Tailwind CSS v4 and shadcn/ui (components in `web/components/ui`).

```bash
cd web
npm install
npx next dev -p 3000        # http://localhost:3000 and http://localhost:3000/app
```

The replay reads `../logs` by default; set `SLIMON_LOG_DIR` to point it at another log, the same variable the agent uses. The ticks in the landing-page animation are illustrative and labelled as such; everything on `/app` comes from the log.

## Decision log record (`slimon.tick/v1`)

`tick_id`, `ts`, `mode`, `config_hash`, `session`, `portfolio`, `closed_trades`, `risk_notes` (breaker trips, cooldown starts), `forced_actions`, `events`, `llm` (model, served_by, request_id, usage, latency, summarized thinking, error), `decision` (the structured object), `risk` (verdict, every check with pass/fail and detail, veto reasons, the sized order intent), `execution` (clientOid, order, status, fill, fee), `portfolio_after`, `risk_state`, `errors`.
