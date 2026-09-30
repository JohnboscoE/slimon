# Run records

Paper trading on **Bitget's demo venue** (USDT-M perpetuals on US stocks), by the agent in this
repository. Submitted for Bitget AI Base Camp Hackathon S2, Track 2: Agentic Trading.

Every file here is derived from `../logs/decisions/*.jsonl` by
[`../slimon/report.py`](../slimon/report.py). Nothing is hand-entered or edited. To rebuild all
three from the raw log and check them yourself:

```bash
python -m slimon report
```

The agent runs unattended on GitHub Actions, commits its own decision log, and regenerates this
folder on every commit — so these files never lag the log, and the git history of
[`../logs/decisions/`](../logs/decisions) shows the record accruing in real time rather than
arriving in one drop.

## The files

### `paper_trades.csv` — one row per order that reached the venue

The required fields, by column name:

| Required field | Column |
|---|---|
| timestamp | `timestamp_utc` — UTC, millisecond precision |
| instrument | `instrument` — e.g. `NVDAUSDT`, `SP500USDT` |
| direction | `direction` — `buy` / `sell`; see also `action` and `position_side` |
| price | `price` — the actual fill price returned by the venue, not the intended price |
| quantity | `quantity` — in contracts, after rounding to the lot step |
| account balance change | `balance_change_usdt`, with `equity_before_usdt` and `equity_after_usdt` |

Also carried, per order: `tick_id` (the tick in the decision log this came from, so any row can be
traced back to the events and reasoning behind it), `action` (`OPEN_LONG` / `OPEN_SHORT` / `CLOSE`),
`position_side`, `notional_usdt`, `fee_usdt`, `status`, `client_oid` (the idempotency key sent to
Bitget), `decided_by` (`model` or `risk_gate`) and `reason`.

Rows with `status` of `rejected` are kept deliberately: an order the venue refused is part of an
honest record, and its `price` and `quantity` are empty because no fill happened.

**On the balance columns.** `equity_before_usdt` and `equity_after_usdt` are account equity read
from the venue either side of the order, and `balance_change_usdt` is their difference. On an open
that difference is mostly the fee; on a close it carries the realised PnL. Because it is equity, it
also moves with any *other* position still open at that tick. For the clean per-trade result, read
`net_pnl_usdt` in `round_trips.csv`.

### `round_trips.csv` — one row per closed position

Each open paired with the close that followed it: `opened` / `closed`, `entry` / `exit`, `quantity`,
`gross_pnl_usdt`, `fees_usdt`, `net_pnl_usdt`, `return_pct`, and `closed_by` — whether the model
decided to close, or the risk gate forced it (hard stop, take profit, maximum holding time).

### `summary.json` - headline figures

Period covered, ticks, decisions, risk-gate verdicts (`PASS` / `VETO` / `NO_ACTION`), orders filled,
net closed PnL, fees, turnover, start and end equity, and the three performance statistics the track
is judged on:

| Field | How it is computed |
|---|---|
| `max_drawdown_pct_live` | Largest peak-to-trough fall in account equity, sampled at every tick of the live demo period |
| `win_rate_pct` | `winning_trips` / `round_trips`, where a win is `net_pnl_usdt > 0` — that is, after both fees |
| `sharpe_annualised_live` | Mean over standard deviation of **daily** equity returns, annualised by the square root of 252, at a zero risk-free rate. Reported with `sharpe_observation_days`, the number of daily returns behind it |

A day's equity mark is its last reading, and days the agent did not run are skipped rather than
carried forward, so a gap spans to the next day present instead of contributing zero returns that
would understate volatility.

`daily_return_mean_pct` and `daily_return_stdev_pct` are the Sharpe's own inputs, published so the
figure can be checked rather than taken on trust.

**Read the Sharpe with its observation count in view, and do not read it as a track record.** Two
weeks of daily marks on a book this lightly exposed produces a very small denominator: the gate caps
one position at 15% of equity and everything open at 40%, equity has moved less than a quarter of a
percent end to end, and maximum drawdown is under 0.2%. Annualising a mean that small over a standard
deviation that small by the square root of 252 yields a large number for arithmetic reasons, not
because the strategy has demonstrated a large risk-adjusted return. The honest summary of the
performance so far is the one in `round_trips.csv`: seven closed positions, two of them winners, and
a **negative** net realised PnL. Equity is nonetheless slightly up because it marks an open position
to market, and that single unrealised winner drives most of the Sharpe. Thirteen daily observations
and seven round trips cannot support an inference either way.

`orders_filled` counts every fill, including closes the risk gate forced on its own (a hard stop,
take profit or maximum holding time), so it can exceed the number of orders the model originated.
That is why the count here can sit one above the executed-trade count on the replay site, which
counts only the model's own passed decisions.

## What the log holds that these files flatten

`paper_trades.csv` only has rows where an order was sent. The decision log behind it has one record
per tick, including the ticks where nothing happened and **every veto** — the model's proposal, each
risk rule with its pass/fail and detail, and the reason the trade was refused. Those are the
interesting ones, and they are readable without any setup at
**[slimon-beta.vercel.app/app](https://slimon-beta.vercel.app/app)**, which opens on the veto cases.
