# Build Spec — Bitget AI Base Camp Hackathon S2

**Track:** Agentic Trading (Track 2)
**Sub-theme:** Event-Driven Agent (named sub-theme, not Open Theme)
**Hard deadline:** 21 September 2026, UTC+8
**Solo build.** Fresh codebase — no code lifted from the S1 entry (ExcelLens).

---

## 0. The one constraint that dominates everything

The track requires a **paper trading log actually run during the competition period**, recommended ≥2 weeks. That log accrues in wall-clock time and **cannot be compressed later**.

Therefore the build order is inverted from normal:

1. Get a crude end-to-end loop writing log entries **first**, even if it is ugly.
2. Improve everything else *around a log that is already running*.

Do not build for a week and then start logging. A short log is survivable; a log started on day 8 is not.

---

## 1. What is being built

An autonomous event-driven trading agent for **US stock instruments on Bitget** (the hackathon theme is AI × US stock trading, including tokenized US stocks / related contract scenarios).

The LLM is the **primary decision-maker**, not an assistant. It senses events, forms a judgment, and issues orders — subject to a deterministic risk layer that can override it.

The loop:

```
event source  →  LLM decision  →  deterministic risk gate  →  execution  →  structured decision log
                                          │
                                          └── veto path (also logged)
```

### The differentiator

Most entries in this track will be *news in → LLM opinion → market order*. The judging criteria explicitly reward three things beyond returns:

- decision explainability
- agent architecture quality
- risk control layer effectiveness

**Build so that the risk layer is the product, not an afterthought.** That is where the scoring headroom is, and it is the part that plays to a backend engineer's strengths rather than to quant intuition.

---

## 2. Components

### 2.1 Perception layer
- One or two event sources, not five. Depth beats breadth here.
- Candidates: macro/news feeds, scheduled economic events, price/volatility triggers on the traded instruments.
- `bitget-signal` research Skills (macro-analyst, market-intel, news-briefing, sentiment-analyst, technical-analysis) require **no account or API key** and can serve as the perception layer. Consider these before writing custom scrapers.
- Every event must be persisted with a timestamp *as received*, so decisions can be shown to be non-retrospective.

### 2.2 Decision layer (LLM)
- Structured output only. The model returns a decision object, never free prose that gets regex-parsed.
- Required fields per decision: intended action, instrument, size, confidence, **reasoning**, and the event IDs that triggered it.
- The model must be able to return **NO_TRADE** as a first-class outcome. No-trade decisions with stated reasoning are more convincing to a judge than a log full of fills.

### 2.3 Risk gate (deterministic — NOT the LLM)
This layer is plain code. The LLM proposes; this vetoes. Minimum:

- position size caps (absolute and as % of account equity)
- per-day drawdown circuit breaker that halts trading when tripped
- cooldown after N consecutive losing decisions
- instrument whitelist — the agent can only touch what it is explicitly allowed to touch
- sanity bounds on order size/price to catch malformed model output

**Every veto is logged with its reason.** These log entries are a deliverable, not noise.

### 2.4 Execution layer
- Bitget UTA v3 REST, demo environment.
- Behind an explicit env gate (see §4) that defaults to blocked.
- Idempotency: never allow a retry to double-submit an order.

### 2.5 Decision log
The core artifact. Append-only, one record per tick, including ticks where nothing happened.

Each record: timestamp, events considered, model decision object (including reasoning), risk-gate verdict (pass/veto + reason), execution result or null.

Commit it to the repo continuously so history shows it accruing in real time. A log that appears in a single commit on day 12 looks generated.

### 2.6 Demo (judge-facing)
- **Must be fully explorable with zero setup.** Judges reviewing dozens of entries will not configure API keys. An entry that only comes alive with credentials is functionally broken.
- Replay the recorded decision log — this is real data, not a simulation, so it is honest and costs nothing.
- Optional live/key mode is a bonus path, never the default.
- Lead the demo with the **veto cases**: "here are the times the model wanted to trade and the risk layer refused, with reasons." That is a stronger 90-second story than a PnL curve from a short paper-trading window.

---

## 3. Credentials & environment

| Key | Permission | Notes |
|---|---|---|
| Bitget **Demo** API key | **read/write** | Virtual funds. Write is required — the agent must place orders. |
| Bitget live key (only if pulling live market context) | **read-only** | Keep separate. Never grant write. |

Both: **no withdrawal permission**, ever. Trade permission and withdraw permission are separate grants — the agent never needs to move funds.

**Bind an IP address** to the key. The logger runs from one machine or one deployment, so this costs nothing and makes a leaked key unusable elsewhere. Matters more than usual with an LLM in the loop and a public repo.

### Demo-mode gotchas that look like broken keys
- Demo key creation: log in → **switch to Demo mode** → Personal Center → API Key Management → create Demo API Key. It is a mode toggle inside the same account; a live account does not block it.
- REST demo calls need the header **`paptrading: 1`** alongside the Demo key. Without it, calls fail in ways that look like an invalid key.
- WebSocket demo uses **different hosts**: `wss://wspap.bitget.com/v3/ws/public` and `wss://wspap.bitget.com/v3/ws/private`. Enabling REST demo mode does **not** switch WS endpoints.
- Alternative path if the demo toggle is unavailable: the **Agentic account via OAuth** (dedicated agent sub-account, fund isolation, quota control, no withdrawals, no manual key). This is the path the hackathon itself recommends.

### Verify before building on it
Confirm **which US-stock instruments actually exist in the Bitget demo environment** before committing the architecture. US stock futures are live with spot on the roadmap, and demo environments often carry a narrower instrument set than production. If the instruments aren't there, the whole premise needs rethinking on day 1, not day 8.

---

## 4. Safety rails in code

- `ENABLE_TRADING=1` env gate, **separate from credentials**, defaulting to off. The difference between "logging decisions" and "placing orders" must be one flag you control, not a property of the key.
- Risk-gate rules enforced in code, never delegated to the model via prompt instructions. A prompt is not a control.
- `.env` never committed. Credentials never logged, never printed, never in the decision log.
- Dry-run mode that runs the full loop and logs what *would* have been submitted.

---

## 5. Required deliverables (track checklist)

- [ ] Runnable Demo — zero setup required
- [ ] Event → decision → execution flow demonstration
- [ ] Paper trading log, actually run during the competition period
- [ ] Compliant X post — must contain `#BitgetHackathon` and `@Bitget_AI`, must substantively introduce the project, and a retweet of the official post. **No X post = invalid submission.**
- [ ] Project description in the Google Form (GitHub README cannot substitute)

### Form fields to not get wrong
- **"Are you an S1 participant/team" = Yes.** This is about the person, not the project. With an unrelated new build, the "Substantive New Additions" answer is simply that this is a new project unrelated to the S1 entry. Do not leave blank, do not answer No.
- **"Role of the LLM in Your Project"** — separate required field.
- Optional but free: "Apply for Demo Day", "Apply for K3 Token Subsidy".

### Project description — six parts, first three weighted most
1. **Thesis** — why built, core hypothesis, signal sources, decision logic, risk controls.
2. **Target user** — a concrete segment (risk appetite, capital size, trading frequency, market, use case). **"All traders" is explicitly rejected.** Decide this early; do not write it the night before.
3. **Validation data** — test period, returns, Sharpe/Sortino, max drawdown, win rate, turnover, fees and slippage. Label every figure as observed / estimated / targeted. Targets are acceptable if labelled as targets.
4. **Progress** — built, not built, problems, fixes, next steps, frameworks/models/APIs.
5. **Deliverables** — list what is behind the submission link.
6. **Take on AI trading** — optional.

**On validation honesty:** the paper-trading window will be short and the resulting Sharpe/win-rate figures are statistically meaningless at that duration. State the window plainly rather than dressing the numbers up, and lean the description on architecture and risk controls. Judges can compute that a 9-day sample proves nothing; pretending otherwise costs more credibility than the short window does.

---

## 6. Sequencing

| Phase | Work |
|---|---|
| **Day 0 (today)** | Demo key + `paptrading` header verified with one signed call. Confirm US-stock instruments exist in demo. Crudest possible loop appending to the log. **Start logging.** |
| **Days 1–3** | Risk gate: sizing caps, drawdown breaker, cooldown, whitelist. Log every veto. |
| **Days 4–8** | Decision explainability — reasoning attached to every record. Judge-facing demo replaying the log. |
| **Days 9–10** | Project description (six parts). X post with required tags. Submission form. |

Leave slack. The form, the X post, and the write-up are not trivial and are the difference between a valid and an invalid submission.

---

## 7. Known risks

- **Log duration is short.** Unavoidable given the start date. Mitigate with honest labelling and by making architecture the headline.
- **Demo instrument coverage** may not include the intended US-stock instruments. Verify day 0.
- **Official dates contradict each other** across the handbook (judge review, voting window, and submission dates each appear with two or three different values). Treat **21 September** as the deadline and confirm anything else in the official Telegram rather than planning around a date from the doc.
- **Qwen credits do not support Claude Code** (Cursor/Codex only), and the setup guide is macOS-only (`launchctl`). On Windows/WSL, budget friction or skip the credits — they are not required to compete.
- **Crowded track.** The S1 entry was a competent, deployed, working dashboard and it placed nowhere. "It works" is not the bar. Doing something most submissions will skip is the bar.
