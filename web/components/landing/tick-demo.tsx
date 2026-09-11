"use client";

import { useEffect, useRef, useState } from "react";
import {
  Check,
  FileText,
  Pause,
  Play,
  Radar,
  Send,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SCENARIOS, type Scenario, type Verdict } from "./tick-scenarios";

const STAGES = [
  { title: "Perceive", icon: Radar, ms: 2200 },
  { title: "Decide", icon: Sparkles, ms: 2800 },
  { title: "Gate", icon: ShieldCheck, ms: 3400 },
  { title: "Execute", icon: Send, ms: 2200 },
  { title: "Log", icon: FileText, ms: 3600 },
] as const;

const LAST = STAGES.length - 1;

export function TickDemo() {
  const [scenarioIdx, setScenarioIdx] = useState(0);
  const [stage, setStage] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [visible, setVisible] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReducedMotion(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  // Start playing when the demo scrolls into view, and stop spending timers when it leaves.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), {
      threshold: 0.25,
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const running = playing && visible && !reducedMotion;

  useEffect(() => {
    if (!running) return;
    const t = window.setTimeout(() => {
      if (stage < LAST) {
        setStage(stage + 1);
      } else {
        setScenarioIdx((i) => (i + 1) % SCENARIOS.length);
        setStage(0);
      }
    }, STAGES[stage].ms);
    return () => window.clearTimeout(t);
  }, [running, stage]);

  const scenario = SCENARIOS[scenarioIdx];
  const shown = reducedMotion ? LAST : stage;

  function pick(i: number) {
    setScenarioIdx(i);
    setStage(0);
  }

  return (
    <div ref={root} className="rounded-2xl border bg-card/60 p-4 shadow-2xl shadow-black/40 backdrop-blur sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Example ticks" className="flex flex-wrap gap-1.5">
          {SCENARIOS.map((s, i) => (
            <button
              key={s.key}
              role="tab"
              aria-selected={i === scenarioIdx}
              onClick={() => pick(i)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                i === scenarioIdx
                  ? "border-primary/50 bg-primary/10 text-foreground"
                  : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[11px] text-muted-foreground">tick {scenario.tickId}</span>
          {!reducedMotion && (
            <button
              onClick={() => setPlaying((p) => !p)}
              aria-label={playing ? "Pause animation" : "Play animation"}
              className="grid size-7 place-items-center rounded-full border text-muted-foreground transition-colors hover:text-foreground"
            >
              {playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            </button>
          )}
        </div>
      </div>

      {/* Progress rail: desktop only, the cards carry their own state on mobile. */}
      <div className="relative mt-6 hidden h-px bg-border lg:block" aria-hidden>
        <div
          className="absolute inset-y-0 left-0 bg-primary transition-[width] duration-700 ease-out"
          style={{ width: `${(shown / LAST) * 100}%` }}
        />
        {running && shown < LAST && (
          <div className="absolute inset-y-0" style={{ left: `${(shown / LAST) * 100}%`, width: `${100 / LAST}%` }}>
            <span className="animate-travel absolute -top-[3px] size-[7px] -translate-x-1/2 rounded-full bg-primary shadow-[0_0_12px_2px] shadow-primary/60" />
          </div>
        )}
      </div>

      <ol className="mt-4 grid gap-3 lg:mt-5 lg:grid-cols-5">
        {STAGES.map((s, i) => (
          <StageCard key={s.title} index={i} title={s.title} icon={s.icon} state={i < shown ? "done" : i === shown ? "active" : "idle"}>
            {i <= shown && <StageBody key={`${scenario.key}-${i}`} stage={i} scenario={scenario} />}
          </StageCard>
        ))}
      </ol>

      <p className="mt-4 text-xs text-muted-foreground">
        Illustrative ticks. Event types, rule names, limits and the veto figures are the agent&apos;s own: the
        vetoed tick reproduces a smoke-test record.
      </p>
    </div>
  );
}

function StageCard({
  index,
  title,
  icon: Icon,
  state,
  children,
}: {
  index: number;
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  state: "idle" | "active" | "done";
  children: React.ReactNode;
}) {
  return (
    <li
      aria-current={state === "active" ? "step" : undefined}
      className={cn(
        // Fixed height on desktop so the page below never jumps as the stages fill in.
        "flex min-h-[9rem] min-w-0 flex-col rounded-xl border p-3.5 transition-[border-color,background-color,opacity] duration-500 lg:h-[30rem]",
        state === "active" && "border-primary/45 bg-primary/[0.04]",
        state === "done" && "bg-background/40",
        state === "idle" && "opacity-45",
      )}
    >
      <div className="flex items-center gap-2 text-xs">
        <span
          className={cn(
            "grid size-6 place-items-center rounded-md border",
            state === "idle" ? "text-muted-foreground" : "border-primary/40 text-primary",
          )}
        >
          <Icon className="size-3.5" />
        </span>
        <span className="font-mono text-muted-foreground">0{index + 1}</span>
        <span className="font-medium">{title}</span>
      </div>
      <div className="mt-3 flex-1 text-[12.5px] leading-relaxed">{children}</div>
    </li>
  );
}

/** The tick id n candles (5 minutes each) before this one, e.g. 20260910T142015 -> 20260910T141515. */
function earlierTick(tickId: string, n: number): string {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$/.exec(tickId);
  if (!m) return tickId;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) - n * 5 * 60_000;
  return new Date(t).toISOString().replace(/[-:]/g, "").slice(0, 15);
}

function stagger(i: number, step = 140) {
  return { animationDelay: `${i * step}ms` };
}

function StageBody({ stage, scenario }: { stage: number; scenario: Scenario }) {
  switch (stage) {
    case 0:
      return (
        <ul className="space-y-2">
          {scenario.events.map((e, i) => (
            <li key={e.id} className="animate-rise rounded-lg border bg-background/50 p-2" style={stagger(i, 380)}>
              <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10.5px] text-primary">{e.type}</span>
                <span className="font-mono text-[10.5px] text-muted-foreground">{e.receivedAt}</span>
              </div>
              <p className="mt-1.5 text-foreground/90">{e.summary}</p>
            </li>
          ))}
        </ul>
      );

    case 1: {
      const d = scenario.decision;
      const fields: [string, string][] = [
        ["action", d.action],
        ["instrument", d.instrument ? d.instrument : '""'],
        ["notional_usdt", String(d.notional_usdt)],
        ["confidence", d.confidence.toFixed(2)],
        ["cites", `${scenario.events.length} event IDs`],
      ];
      return (
        <div className="font-mono text-[11.5px]">
          {fields.map(([k, v], i) => (
            <div key={k} className="animate-rise flex justify-between gap-2" style={stagger(i, 160)}>
              <span className="text-muted-foreground">{k}</span>
              <span className={cn(k === "action" && "text-primary")}>{v}</span>
            </div>
          ))}
          <p className="animate-rise mt-2.5 border-l-2 border-primary/40 pl-2 font-sans text-[12px] text-foreground/85" style={stagger(fields.length, 160)}>
            {scenario.decision.reasoning}
            <span className="animate-caret ml-0.5 inline-block h-3 w-[5px] translate-y-0.5 bg-primary/70" />
          </p>
        </div>
      );
    }

    case 2:
      return (
        <div>
          <ul className="space-y-1">
            {scenario.checks.map((c, i) => (
              <li key={c.check} className="animate-rise flex items-start gap-1.5" style={stagger(i, 170)} title={c.detail}>
                {c.passed ? (
                  <Check className="mt-0.5 size-3.5 shrink-0 text-pass" aria-label="passed" />
                ) : (
                  <X className="mt-0.5 size-3.5 shrink-0 text-veto" aria-label="failed" />
                )}
                <span className="min-w-0">
                  <span className={cn("font-mono text-[11px]", !c.passed && "text-foreground")}>{c.check}</span>
                  {!c.passed && <span className="block text-[11px] text-muted-foreground">{c.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
          {scenario.hiddenPassed > 0 && (
            <p className="animate-rise mt-1.5 text-[11px] text-muted-foreground" style={stagger(scenario.checks.length, 170)}>
              + {scenario.hiddenPassed} more checks passed
            </p>
          )}
          <div className="animate-stamp mt-3" style={stagger(scenario.checks.length + 1, 170)}>
            <VerdictStamp verdict={scenario.verdict} />
          </div>
        </div>
      );

    case 3:
      return (
        <div className="animate-rise">
          <p className="font-medium">{scenario.execution.title}</p>
          <dl className="mt-2 space-y-1.5">
            {scenario.execution.lines.map(([k, v], i) => (
              <div key={k} className="animate-rise" style={stagger(i + 1, 200)}>
                <dt className="text-[11px] text-muted-foreground">{k}</dt>
                <dd className="font-mono text-[11.5px]">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      );

    default: {
      const d = scenario.decision;
      const failed = scenario.checks.filter((c) => !c.passed).length;
      const fields: [string, string][] = [
        ["tick_id", scenario.tickId],
        ["events", String(scenario.events.length)],
        ["decision", [d.action, d.instrument].filter(Boolean).join(" ")],
        ["verdict", scenario.verdict],
        ...(failed ? [["veto_reasons", String(failed)] as [string, string]] : []),
        ["execution", scenario.verdict === "PASS" ? "filled" : "null"],
      ];
      return (
        <div className="animate-rise">
          <p className="font-mono text-[11px] text-muted-foreground">logs/decisions/2026-09-10.jsonl</p>
          <div className="mt-2 overflow-hidden rounded-lg border bg-background/70 font-mono text-[10.5px] leading-[1.6]">
            {[2, 1].map((n) => (
              <p key={n} className="truncate border-b px-2 py-1 text-muted-foreground/60">
                {`{"tick_id":"${earlierTick(scenario.tickId, n)}","llm":{"called":false,"reason":"no_events"}}`}
              </p>
            ))}
            <div className="border-l-2 border-primary bg-primary/[0.05] px-2 py-1.5">
              {fields.map(([k, v], i) => (
                <div key={k} className="animate-rise flex justify-between gap-2" style={stagger(i + 1, 120)}>
                  <span className="text-muted-foreground">{k}</span>
                  <span className="truncate text-foreground/90">{v}</span>
                </div>
              ))}
            </div>
          </div>
          <p className="mt-2.5 text-[11px] leading-relaxed text-muted-foreground">
            One line per tick, including the quiet ones. Nothing is ever rewritten.
          </p>
        </div>
      );
    }
  }
}

export function VerdictStamp({ verdict }: { verdict: Verdict }) {
  const map = {
    PASS: { label: "PASS", icon: Check, cls: "border-pass/50 text-pass" },
    VETO: { label: "VETO", icon: X, cls: "border-veto/50 text-veto" },
    NO_ACTION: { label: "NO ACTION", icon: Check, cls: "border-muted-foreground/40 text-muted-foreground" },
  }[verdict];
  const Icon = map.icon;
  return (
    <span className={cn("inline-flex -rotate-[4deg] items-center gap-1 rounded-md border-2 px-2 py-0.5 font-mono text-xs font-bold tracking-widest", map.cls)}>
      <Icon className="size-3.5" strokeWidth={3} />
      {map.label}
    </span>
  );
}
