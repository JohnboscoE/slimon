/** Shapes shared by the log reader (server) and the replay view (client). No Node imports here. */

export type Verdict = "PASS" | "VETO" | "NO_ACTION";

export interface LogEvent {
  id: string;
  type: string;
  symbol: string | null;
  summary: string;
  receivedAt: string | null;
  sourceTs: string | null;
  /** News events only: the article, its publisher, and the same-symbol shocks seen that tick. */
  url: string | null;
  publisher: string | null;
  confirmation: string[];
}

export interface LogCheck {
  check: string;
  passed: boolean;
  detail: string;
}

export interface TickRow {
  tickId: string;
  ts: string;
  mode: string;
  session: string;
  configHash: string | null;
  events: LogEvent[];
  llm: {
    called: boolean;
    reason: string | null;
    model: string | null;
    servedBy: string | null;
    latencyMs: number | null;
    requestId: string | null;
    error: string | null;
  };
  decision: {
    action: string;
    instrument: string;
    notionalUsdt: number | null;
    confidence: number | null;
    timeHorizonHours: number | null;
    triggeringEventIds: string[];
    reasoning: string;
    invalidation: string;
  } | null;
  risk: { verdict: Verdict; vetoReasons: string[]; checks: LogCheck[] } | null;
  intent: Record<string, unknown> | null;
  execution: {
    status: string | null;
    venue: string | null;
    clientOid: string | null;
    fillPrice: number | null;
    qty: number | null;
    fee: number | null;
  } | null;
  forced: { rule: string; detail: string; status: string | null }[];
  equity: number | null;
  errors: string[];
}

export interface LogSummary {
  dir: string;
  files: number;
  badLines: number;
  first: string | null;
  last: string | null;
  ticks: number;
  decisions: number;
  vetoes: number;
  executed: number;
  stoodAside: number;
  forced: number;
  errorTicks: number;
}

/** Execution statuses that mean an order left (or, in dry_run, would have left) the building. Mirrors FILLED_LIKE in agent.py. */
const EXECUTED = new Set(["filled", "partially_filled", "submitted", "new", "live", "would_submit"]);

export function isExecuted(row: TickRow): boolean {
  return row.risk?.verdict === "PASS" && EXECUTED.has(row.execution?.status ?? "");
}
