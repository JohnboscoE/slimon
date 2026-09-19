"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Check, ChevronDown, Minus, ShieldAlert, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtDate, fmtTime, fmtUsd } from "@/lib/format";
import { isExecuted, type TickRow, type Verdict } from "@/lib/tick";

export type Filter = "veto" | "executed" | "aside" | "decisions" | "all";

const FILTERS: { key: Filter; label: string; test: (r: TickRow) => boolean }[] = [
  { key: "veto", label: "Vetoed", test: (r) => r.risk?.verdict === "VETO" },
  { key: "executed", label: "Executed", test: isExecuted },
  { key: "aside", label: "Stood aside", test: (r) => r.risk?.verdict === "NO_ACTION" },
  { key: "decisions", label: "All decisions", test: (r) => r.decision != null || r.forced.length > 0 },
  { key: "all", label: "Every tick", test: () => true },
];

const PAGE = 50;

export function LogViewer({ rows, defaultFilter }: { rows: TickRow[]; defaultFilter: Filter }) {
  const [filter, setFilter] = useState<Filter>(defaultFilter);
  const [symbol, setSymbol] = useState("all");
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState<Set<string>>(() => new Set());

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.key, rows.filter(f.test).length])) as Record<Filter, number>,
    [rows],
  );
  const symbols = useMemo(
    () => [...new Set(rows.map((r) => r.decision?.instrument).filter((s): s is string => !!s))].sort(),
    [rows],
  );
  const visible = useMemo(() => {
    const test = FILTERS.find((f) => f.key === filter)!.test;
    return rows.filter((r) => test(r) && (symbol === "all" || r.decision?.instrument === symbol));
  }, [rows, filter, symbol]);

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <section className="mt-10" aria-label="Ticks">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Filter ticks" className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => {
                setFilter(f.key);
                setLimit(PAGE);
              }}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                filter === f.key
                  ? "border-primary/50 bg-primary/10 text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {f.label}
              <span className="ml-1.5 tabular-nums text-muted-foreground">{counts[f.key]}</span>
            </button>
          ))}
        </div>
        {symbols.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Instrument
            <select
              value={symbol}
              onChange={(e) => {
                setSymbol(e.target.value);
                setLimit(PAGE);
              }}
              className="h-8 rounded-lg border bg-card px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="all">All</option>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {filter === "veto" && (
        <p className="mt-4 flex items-start gap-2 text-sm text-muted-foreground">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-veto" />
          Times the model wanted to trade and the risk gate refused. Every failed rule is listed, not just the first.
        </p>
      )}

      {visible.length === 0 ? (
        <p className="mt-6 rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
          No ticks match this filter yet.
        </p>
      ) : (
        <ul className="mt-5 divide-y overflow-hidden rounded-xl border">
          {visible.slice(0, limit).map((r) => (
            <TickItem key={r.tickId + r.ts} row={r} open={open.has(r.tickId + r.ts)} onToggle={() => toggle(r.tickId + r.ts)} />
          ))}
        </ul>
      )}

      {visible.length > limit && (
        <div className="mt-4 flex justify-center">
          <button
            onClick={() => setLimit((l) => l + PAGE)}
            className="rounded-lg border px-4 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Show {Math.min(PAGE, visible.length - limit)} more of {visible.length - limit}
          </button>
        </div>
      )}
    </section>
  );
}

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const cfg = {
    PASS: { label: "Pass", icon: Check, cls: "border-pass/40 text-pass" },
    VETO: { label: "Veto", icon: X, cls: "border-veto/40 text-veto" },
    NO_ACTION: { label: "No action", icon: Minus, cls: "text-muted-foreground" },
  }[verdict] ?? { label: verdict, icon: Minus, cls: "text-muted-foreground" };
  const Icon = cfg.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium", cfg.cls)}>
      <Icon className="size-3" strokeWidth={2.5} />
      {cfg.label}
    </span>
  );
}

function headline(r: TickRow): string {
  if (r.risk?.verdict === "VETO" && r.risk.vetoReasons.length) return r.risk.vetoReasons[0];
  if (r.decision?.reasoning) return r.decision.reasoning;
  if (r.forced.length) return r.forced.map((f) => `${f.rule}: ${f.detail}`).join("; ");
  if (r.errors.length) return r.errors[0];
  if (!r.llm.called) {
    const why: Record<string, string> = {
      no_events: "No events on this candle; the model was not called.",
      no_tradable_events: "Events only on watch-only symbols it cannot trade; the model was not called.",
      us_market_closed_and_flat: "Events seen, but the US market was closed and the book was flat.",
      portfolio_unavailable: "Portfolio could not be read; tick skipped.",
    };
    return why[r.llm.reason ?? ""] ?? `Model not called (${r.llm.reason ?? "unknown"}).`;
  }
  if (r.llm.error) return `Model returned no valid decision: ${r.llm.error}`;
  return "";
}

function TickItem({ row: r, open, onToggle }: { row: TickRow; open: boolean; onToggle: () => void }) {
  const d = r.decision;
  const failed = r.risk?.vetoReasons.length ?? 0;
  return (
    <li className="bg-background">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="grid w-full grid-cols-[auto_1fr_auto] items-start gap-x-4 gap-y-1 px-4 py-3.5 text-left transition-colors hover:bg-card/60 sm:grid-cols-[8.5rem_auto_1fr_auto] sm:px-5"
      >
        <span className="font-mono text-[11.5px] leading-5 text-muted-foreground">
          <span className="block text-foreground/85">{fmtTime(r.ts)}</span>
          {fmtDate(r.ts)}
        </span>
        <span className="flex flex-wrap items-center gap-2 sm:min-w-[11rem]">
          {r.risk ? <VerdictBadge verdict={r.risk.verdict} /> : <span className="text-[11px] text-muted-foreground">{r.session}</span>}
          {d && (
            <span className="font-mono text-xs">
              {d.action}
              {d.instrument && <span className="text-muted-foreground"> {d.instrument}</span>}
            </span>
          )}
          {r.forced.length > 0 && (
            <span className="rounded-md border border-primary/40 px-1.5 py-0.5 text-[11px] text-primary">Gate closed a position</span>
          )}
        </span>
        <span className="col-span-3 min-w-0 text-sm leading-relaxed text-muted-foreground sm:col-span-1">
          <span className="line-clamp-2">
            {r.errors.length > 0 && <AlertTriangle className="mr-1 inline size-3.5 -translate-y-px text-primary" aria-label="errors" />}
            {headline(r)}
            {failed > 1 && <span className="text-foreground/70"> (+{failed - 1} more)</span>}
          </span>
        </span>
        <ChevronDown
          className={cn(
            "col-start-3 row-start-1 mt-0.5 size-4 text-muted-foreground transition-transform sm:col-start-4",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>
      {open && <TickDetail row={r} />}
    </li>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{label}</p>
      <div className="mt-1.5 text-sm leading-relaxed">{children}</div>
    </div>
  );
}

function TickDetail({ row: r }: { row: TickRow }) {
  const d = r.decision;
  const cited = new Set(d?.triggeringEventIds ?? []);
  return (
    <div className="grid gap-6 border-t bg-card/30 px-4 py-5 sm:px-5 lg:grid-cols-2">
      <div className="space-y-5">
        {d && (
          <>
            <Field label="Proposal">
              <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs">
                <span>{d.action}</span>
                {d.instrument && <span>{d.instrument}</span>}
                <span>notional {fmtUsd(d.notionalUsdt)} USDT</span>
                <span>confidence {d.confidence?.toFixed(2) ?? "-"}</span>
                {d.timeHorizonHours != null && <span>horizon {d.timeHorizonHours}h</span>}
              </div>
            </Field>
            <Field label="Reasoning">
              <p className="text-foreground/90">{d.reasoning}</p>
            </Field>
            {d.invalidation && (
              <Field label="Would be wrong if">
                <p className="text-foreground/90">{d.invalidation}</p>
              </Field>
            )}
          </>
        )}
        <Field label={`Events seen (${r.events.length})`}>
          {r.events.length === 0 ? (
            <p className="text-muted-foreground">None.</p>
          ) : (
            <ul className="space-y-2">
              {r.events.map((e) => (
                <li key={e.id} className="rounded-lg border bg-background/60 p-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10.5px] text-primary">{e.type}</span>
                    {cited.has(e.id) && <span className="text-[11px] text-foreground/70">cited</span>}
                  </div>
                  <p className="mt-1.5">{e.summary}</p>
                  {e.type === "news" && (
                    <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                      {e.url && /^https?:\/\//.test(e.url) && (
                        <a href={e.url} target="_blank" rel="noopener noreferrer nofollow" className="text-primary underline-offset-2 hover:underline">
                          Read the article
                        </a>
                      )}
                      <span className={e.confirmation.length ? "text-pass" : "text-muted-foreground"}>
                        {e.confirmation.length ? `Market confirmed: ${e.confirmation.join("; ")}` : "No market reaction this tick"}
                      </span>
                    </p>
                  )}
                  <p className="mt-1 font-mono text-[10.5px] text-muted-foreground">
                    received {fmtTime(e.receivedAt)}
                    {e.sourceTs && <> · candle {fmtTime(e.sourceTs)}</>}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Field>
      </div>

      <div className="space-y-5">
        {r.risk && (
          <Field label={`Risk gate (${r.risk.checks.filter((c) => c.passed).length} of ${r.risk.checks.length} passed)`}>
            <ul className="divide-y rounded-lg border bg-background/60">
              {[...r.risk.checks].sort((a, b) => Number(a.passed) - Number(b.passed)).map((c) => (
                <li key={c.check} className="flex items-start gap-2 px-2.5 py-2">
                  {c.passed ? (
                    <Check className="mt-0.5 size-3.5 shrink-0 text-pass" aria-label="passed" />
                  ) : (
                    <X className="mt-0.5 size-3.5 shrink-0 text-veto" aria-label="failed" />
                  )}
                  <div className="min-w-0">
                    <p className="font-mono text-[11.5px]">{c.check}</p>
                    <p className="text-xs break-words text-muted-foreground">{c.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          </Field>
        )}
        {r.forced.length > 0 && (
          <Field label="Closed by the gate, without the model">
            <ul className="space-y-1 text-sm">
              {r.forced.map((f, i) => (
                <li key={i}>
                  <span className="font-mono text-xs">{f.rule}</span>{" "}
                  <span className="text-muted-foreground">{f.detail}</span>
                  {f.status && <span className="font-mono text-xs text-muted-foreground"> · {f.status}</span>}
                </li>
              ))}
            </ul>
          </Field>
        )}
        {r.execution && (
          <Field label="Execution">
            <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs">
              <span>{r.execution.status}</span>
              {r.execution.venue && <span>{r.execution.venue}</span>}
              {r.execution.qty != null && <span>qty {r.execution.qty}</span>}
              {r.execution.fillPrice != null && <span>@ {r.execution.fillPrice}</span>}
              {r.execution.fee != null && <span>fee {r.execution.fee}</span>}
              {r.execution.clientOid && <span className="text-muted-foreground">{r.execution.clientOid}</span>}
            </div>
          </Field>
        )}
        {r.errors.length > 0 && (
          <Field label="Errors">
            <ul className="space-y-1 font-mono text-xs break-words text-muted-foreground">
              {r.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </Field>
        )}
        <Field label="Record">
          <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-muted-foreground">
            <span>tick {r.tickId}</span>
            <span>{r.mode}</span>
            <span>session {r.session}</span>
            {r.configHash && <span>config {r.configHash}</span>}
            {r.llm.servedBy && <span>{r.llm.servedBy}</span>}
            {r.llm.latencyMs != null && <span>{(r.llm.latencyMs / 1000).toFixed(1)}s</span>}
            {r.llm.requestId && <span className="break-all">{r.llm.requestId}</span>}
            {r.equity != null && <span>equity {fmtUsd(r.equity)}</span>}
          </div>
        </Field>
      </div>
    </div>
  );
}
