import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, Check, X } from "lucide-react";
import { LogViewer, type Filter } from "@/components/app/log-viewer";
import { readDecisionLog } from "@/lib/decision-log";
import { fmtCount, fmtDate } from "@/lib/format";

export const metadata: Metadata = {
  title: "Decision log | Slimon",
  description: "Replay every tick Slimon has logged: the events it saw, what the LLM proposed, and what the risk gate allowed.",
};

// The agent appends to the log while this page is open; read it on every request.
export const dynamic = "force-dynamic";

export default function AppPage() {
  const { rows, summary } = readDecisionLog();
  const defaultFilter: Filter = summary.vetoes > 0 ? "veto" : summary.decisions > 0 ? "decisions" : "all";
  const period =
    summary.first && summary.last
      ? fmtDate(summary.first) === fmtDate(summary.last)
        ? fmtDate(summary.last)
        : `${fmtDate(summary.first)} to ${fmtDate(summary.last)}`
      : null;

  return (
    <main className="flex-1">
      <header className="sticky top-0 z-20 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="size-5 rounded-full bg-black shadow-[0_0_0_1.5px_var(--primary),0_0_12px_2px_oklch(0.8_0.15_65/0.45)]" />
            <span className="text-sm font-semibold tracking-tight">Slimon</span>
            <span className="text-sm text-muted-foreground">/ Decision log</span>
          </Link>
          <Link href="/" className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="size-3.5" />
            <span className="hidden sm:inline">About Slimon</span>
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl tracking-tight sm:text-5xl">Decision log</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {period ? (
                <>
                  {period} · {fmtCount(summary.ticks)} ticks from {summary.files} daily {summary.files === 1 ? "file" : "files"}
                </>
              ) : (
                "Nothing logged yet"
              )}
            </p>
          </div>
          <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
            Read straight from the agent&apos;s append-only log. Nothing here is simulated or edited.
          </p>
        </div>

        {summary.ticks === 0 ? (
          <EmptyState dir={summary.dir} />
        ) : (
          <>
            <dl className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Ticks logged" value={summary.ticks} />
              <Stat label="Decisions" value={summary.decisions} />
              <Stat label="Vetoed by the gate" value={summary.vetoes} tone="veto" />
              <Stat label="Executed" value={summary.executed} tone="pass" />
              <Stat label="Stood aside" value={summary.stoodAside} />
              <Stat label="Ticks with errors" value={summary.errorTicks} />
            </dl>
            {summary.badLines > 0 && (
              <p className="mt-3 text-xs text-muted-foreground">
                {summary.badLines} unreadable {summary.badLines === 1 ? "line was" : "lines were"} skipped.
              </p>
            )}
            <LogViewer rows={rows} defaultFilter={defaultFilter} />
          </>
        )}
      </div>
    </main>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "pass" | "veto" }) {
  return (
    <div className="bg-background p-4 sm:p-5">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {tone === "veto" && <X className="size-3.5 text-veto" aria-hidden />}
        {tone === "pass" && <Check className="size-3.5 text-pass" aria-hidden />}
        {label}
      </dt>
      <dd className="mt-2 text-2xl font-semibold tabular-nums">{fmtCount(value)}</dd>
    </div>
  );
}

function EmptyState({ dir }: { dir: string }) {
  return (
    <div className="mt-10 rounded-2xl border border-dashed p-8 sm:p-12">
      <div className="mx-auto size-12 rounded-full bg-black shadow-[0_0_0_1.5px_var(--primary),0_0_22px_4px_oklch(0.8_0.15_65/0.35)]" />
      <h2 className="mt-6 text-center text-lg font-medium">No ticks logged yet</h2>
      <p className="mx-auto mt-2 max-w-md text-center text-sm leading-relaxed text-muted-foreground">
        This page replays the agent&apos;s decision log. It fills in as soon as the agent starts running: one record per
        closed 5-minute candle.
      </p>
      <div className="mx-auto mt-6 max-w-lg space-y-3 text-sm">
        <div className="overflow-x-auto rounded-lg border bg-card/60 p-4">
          <pre className="font-mono text-[12.5px] leading-relaxed text-foreground/85">{`.venv/Scripts/python -m slimon check --llm
.venv/Scripts/python -m slimon run`}</pre>
        </div>
        <p className="text-xs text-muted-foreground">
          Looking in <code className="font-mono break-all text-foreground/80">{dir}</code>. Set{" "}
          <code className="font-mono text-foreground/80">SLIMON_LOG_DIR</code> to read a different log.
        </p>
      </div>
    </div>
  );
}
