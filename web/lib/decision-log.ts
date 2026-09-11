/**
 * Reads the agent's append-only decision log (slimon.tick/v1, one JSON object per
 * line, one file per UTC day) and trims each record to what the replay view shows.
 * The Python side is the only writer; this never modifies anything.
 */

import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { isExecuted, type LogSummary, type TickRow, type Verdict } from "./tick";

export function logDir(): string {
  return process.env.SLIMON_LOG_DIR
    ? path.resolve(process.env.SLIMON_LOG_DIR)
    : path.resolve(process.cwd(), "..", "logs");
}

type Json = Record<string, unknown>;

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const obj = (v: unknown): Json | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function toRow(r: Json): TickRow {
  const llm = obj(r.llm) ?? {};
  const d = obj(r.decision);
  const risk = obj(r.risk);
  const ex = obj(r.execution);
  const portfolio = obj(r.portfolio_after) ?? obj(r.portfolio);
  return {
    tickId: str(r.tick_id) ?? "",
    ts: str(r.ts) ?? "",
    mode: str(r.mode) ?? "",
    session: str(r.session) ?? "",
    configHash: str(r.config_hash),
    events: arr(r.events).map((e) => {
      const o = obj(e) ?? {};
      return {
        id: str(o.id) ?? "",
        type: str(o.type) ?? "",
        symbol: str(o.symbol),
        summary: str(o.summary) ?? "",
        receivedAt: str(o.received_at),
        sourceTs: str(o.source_ts),
      };
    }),
    llm: {
      called: llm.called === true,
      reason: str(llm.reason),
      model: str(llm.model),
      servedBy: str(llm.served_by),
      latencyMs: num(llm.latency_ms),
      requestId: str(llm.request_id),
      error: str(llm.error),
    },
    decision: d
      ? {
          action: str(d.action) ?? "",
          instrument: str(d.instrument) ?? "",
          notionalUsdt: num(d.notional_usdt),
          confidence: num(d.confidence),
          timeHorizonHours: num(d.time_horizon_hours),
          triggeringEventIds: arr(d.triggering_event_ids).filter((x): x is string => typeof x === "string"),
          reasoning: str(d.reasoning) ?? "",
          invalidation: str(d.invalidation) ?? "",
        }
      : null,
    risk: risk
      ? {
          verdict: (str(risk.verdict) ?? "NO_ACTION") as Verdict,
          vetoReasons: arr(risk.veto_reasons).filter((x): x is string => typeof x === "string"),
          checks: arr(risk.checks).map((c) => {
            const o = obj(c) ?? {};
            return { check: str(o.check) ?? "", passed: o.passed === true, detail: str(o.detail) ?? "" };
          }),
        }
      : null,
    intent: obj(risk?.intent),
    execution: ex
      ? {
          status: str(ex.status),
          venue: str(ex.venue),
          clientOid: str(ex.client_oid),
          fillPrice: num(ex.fill_price),
          qty: num(ex.qty),
          fee: num(ex.fee),
        }
      : null,
    forced: arr(r.forced_actions).map((f) => {
      const o = obj(f) ?? {};
      return { rule: str(o.rule) ?? "", detail: str(o.detail) ?? "", status: str(obj(o.execution)?.status) };
    }),
    equity: num(portfolio?.equity),
    errors: arr(r.errors).filter((x): x is string => typeof x === "string"),
  };
}

export function readDecisionLog(): { rows: TickRow[]; summary: LogSummary } {
  const dir = path.join(logDir(), "decisions");
  const rows: TickRow[] = [];
  let files: string[] = [];
  let badLines = 0;

  if (existsSync(dir)) {
    files = readdirSync(dir).filter((f) => /^\d{4}-\d{2}-\d{2}\.jsonl$/.test(f)).sort();
    for (const f of files) {
      for (const line of readFileSync(path.join(dir, f), "utf-8").split("\n")) {
        if (!line.trim()) continue;
        try {
          const rec = JSON.parse(line);
          if (obj(rec)) rows.push(toRow(rec as Json));
          else badLines++;
        } catch {
          badLines++; // a torn final line if the agent is mid-write; skip it
        }
      }
    }
  }

  rows.sort((a, b) => (a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0));

  return {
    rows,
    summary: {
      dir,
      files: files.length,
      badLines,
      first: rows.at(-1)?.ts ?? null,
      last: rows[0]?.ts ?? null,
      ticks: rows.length,
      decisions: rows.filter((r) => r.decision).length,
      vetoes: rows.filter((r) => r.risk?.verdict === "VETO").length,
      executed: rows.filter(isExecuted).length,
      stoodAside: rows.filter((r) => r.risk?.verdict === "NO_ACTION").length,
      forced: rows.reduce((n, r) => n + r.forced.length, 0),
      errorTicks: rows.filter((r) => r.errors.length > 0).length,
    },
  };
}
