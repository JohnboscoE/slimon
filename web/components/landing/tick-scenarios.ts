/**
 * The three ticks the landing-page animation plays. They are illustrative, but
 * nothing in them is invented vocabulary: event types, check names, detail
 * strings and limits are the agent's own (slimon/perception.py, slimon/risk.py,
 * config/agent.toml). The veto tick reproduces the smoke-test record quoted in
 * the README.
 */

export type Verdict = "PASS" | "VETO" | "NO_ACTION";

export interface ScenarioEvent {
  id: string;
  type: string;
  symbol: string | null;
  summary: string;
  receivedAt: string;
}

export interface ScenarioCheck {
  check: string;
  passed: boolean;
  detail: string;
}

export interface Scenario {
  key: string;
  label: string;
  tickId: string;
  session: string;
  events: ScenarioEvent[];
  decision: {
    action: "OPEN_LONG" | "OPEN_SHORT" | "CLOSE" | "NO_TRADE";
    instrument: string;
    notional_usdt: number;
    confidence: number;
    reasoning: string;
  };
  checks: ScenarioCheck[];
  /** Checks that also ran and passed but are not drawn, to keep the card short. */
  hiddenPassed: number;
  verdict: Verdict;
  execution: { title: string; lines: [string, string][] };
}

export const SCENARIOS: Scenario[] = [
  {
    key: "veto",
    label: "Vetoed",
    tickId: "20260910T142015",
    session: "regular",
    events: [
      {
        id: "evt-price_move-MSTRUSDT-1789050900000",
        type: "price_move",
        symbol: "MSTRUSDT",
        summary: "MSTRUSDT +2.41% over 30m on the live venue",
        receivedAt: "14:20:15Z",
      },
      {
        id: "evt-volume_spike-MSTRUSDT-1789050900000",
        type: "volume_spike",
        symbol: "MSTRUSDT",
        summary: "MSTRUSDT 5m volume 6.3x median",
        receivedAt: "14:20:15Z",
      },
    ],
    decision: {
      action: "OPEN_LONG",
      instrument: "MSTRUSDT",
      notional_usdt: 5000,
      confidence: 0.64,
      reasoning:
        "Idiosyncratic breakout on 6x volume while the index is flat. Momentum continuation likely over the next few hours.",
    },
    checks: [
      { check: "schema.event_ids_grounded", passed: true, detail: "all cited event IDs were provided this tick" },
      { check: "kill_switch", passed: true, detail: "not engaged" },
      { check: "whitelist", passed: false, detail: "'MSTRUSDT' is NOT on the trading whitelist" },
      { check: "session_open", passed: true, detail: "US session='regular'" },
      { check: "min_confidence", passed: true, detail: "confidence 0.64 vs minimum 0.55" },
      { check: "max_order_notional", passed: false, detail: "5000.00 vs cap 1500 USDT" },
      { check: "position_cap", passed: false, detail: "position would be 5000.00 vs 15% of equity = 1499.84" },
      { check: "gross_exposure_cap", passed: false, detail: "gross exposure would be 5999.71 vs 40% of equity = 3999.56" },
    ],
    hiddenPassed: 14,
    verdict: "VETO",
    execution: {
      title: "Nothing sent",
      lines: [
        ["orders", "0"],
        ["rules failed", "4 of 22"],
        ["model told", "next tick, via recent_decisions"],
      ],
    },
  },
  {
    key: "pass",
    label: "Executed",
    tickId: "20260910T153515",
    session: "regular",
    events: [
      {
        id: "evt-price_move-NVDAUSDT-1789055400000",
        type: "price_move",
        symbol: "NVDAUSDT",
        summary: "NVDAUSDT +1.32% over 30m on the live venue",
        receivedAt: "15:35:15Z",
      },
      {
        id: "evt-range_expansion-NVDAUSDT-1789055400000",
        type: "range_expansion",
        symbol: "NVDAUSDT",
        summary: "NVDAUSDT 5m range 3.4x its 40-candle average",
        receivedAt: "15:35:15Z",
      },
    ],
    decision: {
      action: "OPEN_LONG",
      instrument: "NVDAUSDT",
      notional_usdt: 900,
      confidence: 0.61,
      reasoning:
        "NVDA leads a broad semis bid; NDX100 confirms at +0.6%. Sized well under the cap: conviction is moderate.",
    },
    checks: [
      { check: "schema.event_ids_grounded", passed: true, detail: "all cited event IDs were provided this tick" },
      { check: "whitelist", passed: true, detail: "'NVDAUSDT' is on the trading whitelist" },
      { check: "daily_drawdown_breaker", passed: true, detail: "drawdown +0.21% vs limit -3.0%" },
      { check: "min_confidence", passed: true, detail: "confidence 0.61 vs minimum 0.55" },
      { check: "max_order_notional", passed: true, detail: "900.00 vs cap 1500 USDT" },
      { check: "position_cap", passed: true, detail: "position would be 900.00 vs 15% of equity = 1503.15" },
      { check: "spread_sanity", passed: true, detail: "demo spread 0.041% vs max 0.3%" },
      { check: "venue_divergence", passed: true, detail: "demo vs live 0.118% vs max ±1.5%" },
    ],
    hiddenPassed: 14,
    verdict: "PASS",
    execution: {
      title: "Sent to Bitget demo",
      lines: [
        ["order", "buy 4.9 NVDAUSDT, market"],
        ["clientOid", "slm20260910T153515d"],
        ["hard stop", "-2.5%, preset on exchange"],
      ],
    },
  },
  {
    key: "no-trade",
    label: "Stood aside",
    tickId: "20260910T133515",
    session: "regular",
    events: [
      {
        id: "evt-us_regular_open-mkt-2026-09-10",
        type: "us_regular_open",
        symbol: null,
        summary: "US regular session opened",
        receivedAt: "13:35:15Z",
      },
      {
        id: "evt-volume_spike-TSLAUSDT-1789047000000",
        type: "volume_spike",
        symbol: "TSLAUSDT",
        summary: "TSLAUSDT 5m volume 4.6x median",
        receivedAt: "13:35:15Z",
      },
    ],
    decision: {
      action: "NO_TRADE",
      instrument: "",
      notional_usdt: 0,
      confidence: 0.72,
      reasoning:
        "Opening-auction volume is lifting every name at once; TSLA is not moving apart from the index. Nothing to act on yet.",
    },
    checks: [
      { check: "schema.action", passed: true, detail: "action='NO_TRADE'" },
      { check: "schema.confidence_range", passed: true, detail: "confidence=0.72" },
      { check: "schema.event_ids_grounded", passed: true, detail: "all cited event IDs were provided this tick" },
    ],
    hiddenPassed: 0,
    verdict: "NO_ACTION",
    execution: {
      title: "No order needed",
      lines: [
        ["orders", "0"],
        ["logged as", "a first-class decision"],
        ["reasoning", "published with the record"],
      ],
    },
  },
];
