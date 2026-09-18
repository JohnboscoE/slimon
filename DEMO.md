# Demo video script (90 seconds)

For the hackathon submission. Written to be pasted into a video tool scene by scene: each scene
gives the visual, the on-screen text, and the narration. Keep the voice plain; the log does the
arguing.

**Before recording, refresh every number below** from the live log:

```bash
python -m slimon stats    # if added; otherwise read logs/decisions/*.jsonl
```

Figures below are from **11-18 September 2026**: 206 ticks, 60 decisions, 5 vetoes, 5 filled
orders, equity 49,984 -> 49,945 USDT on the Bitget demo venue.

---

## Scene 1 - The claim (0:00-0:12)

**Visual:** the landing page hero, black hole slowly turning.
**On screen:** `The model proposes. The risk gate decides.`
**Narration:**
> Most trading agents wire a model's opinion straight to an order. Slimon does the opposite. The
> model proposes; code the model cannot argue with decides.

## Scene 2 - One tick (0:12-0:32)

**Visual:** the landing page's tick animation, playing the vetoed scenario end to end.
**On screen, as each card fills:** `Perceive -> Decide -> Gate -> Execute -> Log`
**Narration:**
> Every five minutes, on a closed candle: detectors turn live Bitget market data into timestamped
> events. The model gets those events, the cross-section, the portfolio and the limits, and returns
> one structured decision with its reasoning. Then the gate runs twenty-two rules on it.

## Scene 3 - The veto (0:32-0:52)

**Visual:** `/app` on the Vetoed tab, one veto expanded so the failed rules are legible.
**On screen:** `5 vetoes in 8 days - every failed rule recorded`
**Narration:**
> This is the part most submissions skip. The model wanted to buy COIN. COIN is watched but not on
> the tradable whitelist, so the gate refused, and wrote down why. Every rule that ran is in the
> record, not just the first one that failed. A veto is a deliverable here, not an error.

## Scene 4 - When it does trade (0:52-1:10)

**Visual:** `/app` on the Executed tab; expand the NDX100 pair of records (open 10:15, close 12:25).
**On screen:** `Stop -2.5% and target +5%, preset on the exchange`
**Narration:**
> When a proposal passes, the order goes to Bitget's demo venue with an idempotent client order ID,
> a stop two and a half percent away and a target at five, both preset on the exchange so they hold
> even if the agent stops. This position was closed by the model itself, and the reason it gave is
> in the log next to the fill.

## Scene 5 - The log (1:10-1:25)

**Visual:** scroll `logs/decisions/2026-09-18.jsonl`, then the GitHub commit history of the log.
**On screen:** `206 ticks - including the quiet ones`
**Narration:**
> One line per tick, including the ticks where nothing happened and the model was never called.
> Each record carries the events with their receipt times, the model's reasoning, every rule result,
> the order, and the hash of the config it ran under. It is committed as it accrues, so the history
> shows it was written in real time, not assembled afterwards.

## Scene 6 - Close (1:25-1:30)

**Visual:** landing page, Launch App button, then the deployed URL.
**On screen:** the live URL + `Runs unattended on GitHub Actions`
**Narration:**
> It runs itself, and every decision it has ever made is open to read.

---

## Shot list

| # | Capture | Where |
|---|---|---|
| 1 | Hero, 6s of the idle animation | landing page, top |
| 2 | Tick animation, full cycle on "Vetoed" | landing page, "One tick, start to finish" |
| 3 | Veto expanded, checks visible | `/app`, Vetoed tab, tick `20260914T134515` |
| 4 | Executed tab, NDX100 open and close | `/app`, Executed tab |
| 5 | Raw JSONL scroll + GitHub commit list | editor + repo commits |
| 6 | Landing page footer with the live URL | landing page |

## Facts that must stay accurate

- The log is short and says so: the agent began logging on 11 September 2026.
- Trading is on Bitget's **demo** venue; no code path reaches live trading, and the API key has no
  withdraw permission.
- The decision model is Qwen (`qwen3.8-max`) through the hackathon gateway; earlier records in the
  log were decided by Claude (`claude-opus-5`), and the provider of each record is in the record.
- Results so far are roughly flat-to-slightly-down on virtual money over a handful of trades: far
  too small a sample to describe as performance. Say so rather than implying an edge.
