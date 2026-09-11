import Link from "next/link";
import {
  ArrowRight,
  Clock,
  FileText,
  Fingerprint,
  KeyRound,
  Radar,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { HeroBackdrop } from "@/components/landing/hero-backdrop";
import { TickDemo } from "@/components/landing/tick-demo";
import { cn } from "@/lib/utils";

/* Limits mirror config/agent.toml. If you change the config, change these too. */
const RULES: { name: string; value: string; detail: string }[] = [
  { name: "whitelist", value: "8 of 12", detail: "Perception watches 12 stock perps; only 8 may be traded." },
  { name: "min_confidence", value: "≥ 0.55", detail: "Proposals below this calibrated confidence are refused." },
  { name: "max_order_notional", value: "1,500 USDT", detail: "Absolute cap on any single order." },
  { name: "position_cap", value: "15% equity", detail: "Cap on one position, including what is already held." },
  { name: "gross_exposure_cap", value: "40% equity", detail: "Cap on everything open at once." },
  { name: "max_open_positions", value: "3", detail: "No more than three names held at a time." },
  { name: "daily_drawdown_breaker", value: "−3%", detail: "Down 3% on the UTC day halts new positions until midnight." },
  { name: "loss_cooldown", value: "3 → 4h", detail: "Three losing trades in a row pause new positions for four hours." },
  { name: "max_trades_per_day", value: "8", detail: "Plus 60 minutes minimum between trades in the same symbol." },
  { name: "session_open", value: "pre · regular · post", detail: "No new positions overnight or at weekends." },
  { name: "spread · divergence", value: "0.30% · 1.5%", detail: "Refuses a broken demo book, or one priced far from the live market." },
  { name: "schema.event_ids_grounded", value: "every ID", detail: "Each cited event must be one the agent actually saw this tick." },
];

const STEPS = [
  {
    icon: Radar,
    title: "Perceive",
    body: "Live Bitget market data for twelve US-stock perpetuals, from NVDA and TSLA to the S&P 500 and Nasdaq 100. Deterministic detectors run on closed 5-minute candles: a 1% move in 30 minutes, a candle 3× its average range, volume 4× the median, the US open and close, and reviews of held positions. Each event is stamped the moment it is received.",
  },
  {
    icon: Sparkles,
    title: "Decide",
    body: "Claude gets the events, the full cross-section, the portfolio, the risk limits and its own recent decisions, and returns exactly one decision in a fixed JSON schema: open long, open short, close or no trade, with size, confidence, reasoning, the event IDs behind it, and what would prove it wrong.",
  },
  {
    icon: ShieldCheck,
    title: "Gate",
    body: "Plain code with no model in it. Every rule runs on every proposal and every result is recorded, not just the first failure. One failed rule is a veto. Closing a position reduces risk, so no rule ever blocks a close.",
  },
  {
    icon: Send,
    title: "Execute",
    body: "Orders go to Bitget's demo venue with an idempotent client order ID, so a retry can never double-submit. An ambiguous failure is looked up before anything is resent. Every open carries a hard stop preset on the exchange.",
  },
  {
    icon: FileText,
    title: "Log",
    body: "One JSON line per tick, including the ticks where nothing happened. The log is append-only and committed to the repository as it grows, so its history shows it accruing in real time.",
  },
];

const VETO_RECORD = `decision=OPEN_LONG MSTRUSDT | gate=VETO |
  whitelist: 'MSTRUSDT' is NOT on the trading whitelist;
  max_order_notional: 5000.00 vs cap 1500 USDT;
  position_cap: position would be 5000.00 vs 15% of equity = 1499.84;
  gross_exposure_cap: gross exposure would be 5999.71 vs 40% of equity = 3999.56`;

function LaunchButton({ className, label = "Launch App" }: { className?: string; label?: string }) {
  return (
    <Link href="/app" className={cn(buttonVariants({ size: "lg" }), "group/launch h-10 gap-2 px-4", className)}>
      {label}
      <ArrowRight className="transition-transform group-hover/launch:translate-x-0.5" />
    </Link>
  );
}

function SectionHeading({ eyebrow, title, children }: { eyebrow: string; title: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="max-w-2xl">
      <p className="font-mono text-xs tracking-widest text-primary uppercase">{eyebrow}</p>
      <h2 className="mt-3 font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">{title}</h2>
      {children && <p className="mt-4 text-base leading-relaxed text-muted-foreground">{children}</p>}
    </div>
  );
}

export default function Home() {
  return (
    <main className="flex-1">
      <header className="absolute inset-x-0 top-0 z-20">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5 sm:px-8">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="relative grid size-6 place-items-center rounded-full bg-black shadow-[0_0_0_1.5px_var(--primary),0_0_14px_2px_oklch(0.8_0.15_65/0.5)]" />
            <span className="text-[15px] font-semibold tracking-tight">Slimon</span>
          </Link>
          <div className="flex items-center gap-1 sm:gap-6">
            <div className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
              <a href="#how" className="transition-colors hover:text-foreground">How it works</a>
              <a href="#data" className="transition-colors hover:text-foreground">Data</a>
              <a href="#gate" className="transition-colors hover:text-foreground">Risk gate</a>
              <a href="#log" className="transition-colors hover:text-foreground">Decision log</a>
            </div>
            <LaunchButton className="h-8 px-3" />
          </div>
        </nav>
      </header>

      <HeroBackdrop className="min-h-[100svh]">
        <div className="mx-auto flex min-h-[100svh] max-w-6xl flex-col justify-center px-5 pt-28 pb-24 sm:px-8">
          <div className="max-w-2xl">
            <p className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-muted-foreground backdrop-blur">
              <span className="size-1.5 rounded-full bg-primary" />
              Event-driven trading agent · US-stock perpetuals on Bitget
            </p>
            <h1 className="mt-6 font-display text-[3.4rem] leading-[0.98] tracking-tight sm:text-7xl lg:text-[5.5rem]">
              The model proposes.
              <br />
              The <em className="text-primary">risk gate</em> decides.
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-foreground/75">
              Slimon watches twelve US-stock perpetuals for market events, asks Claude for one structured decision, and
              runs that decision past 22 deterministic rules before anything reaches the exchange. Every tick is logged,
              including every trade it refused.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-3">
              <LaunchButton />
              <a href="#demo" className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-10 px-4")}>
                Watch a tick
              </a>
            </div>
            <ul className="mt-10 flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
              <li>Demo venue only</li>
              <li>Keys without withdraw permission</li>
              <li>Append-only decision log</li>
            </ul>
          </div>
        </div>
      </HeroBackdrop>

      <section id="demo" className="scroll-mt-10 px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <SectionHeading eyebrow="See it work" title="One tick, start to finish">
            Every five minutes, on a closed candle, the same pipeline runs. Most ticks end quietly. When something
            happens, this is the path it takes, and the gate has the last word.
          </SectionHeading>
          <div className="mt-12">
            <TickDemo />
          </div>
        </div>
      </section>

      <section id="how" className="scroll-mt-10 border-t px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <SectionHeading eyebrow="What Slimon does" title="An agent you can audit, one decision at a time">
            Most trading bots are a model&apos;s opinion wired straight to an order. Slimon puts Claude in charge of
            judgement and takes it out of charge of risk. The model sees the market and makes the call. Code it cannot
            talk its way past decides whether the call is allowed.
          </SectionHeading>
          <ol className="mt-14 grid gap-px overflow-hidden rounded-2xl border bg-border md:grid-cols-2 lg:grid-cols-5">
            {STEPS.map((s, i) => (
              <li key={s.title} className="bg-background p-6">
                <div className="flex items-center gap-2.5">
                  <s.icon className="size-4 text-primary" />
                  <span className="font-mono text-xs text-muted-foreground">0{i + 1}</span>
                </div>
                <h3 className="mt-4 text-lg font-medium">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{s.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="data" className="scroll-mt-10 border-t px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <SectionHeading
            eyebrow="Where the signal comes from"
            title={<>It doesn&apos;t read the headline. It reads the <em className="text-primary">market&apos;s answer</em>.</>}
          >
            Slimon perceives through one source: Bitget&apos;s live market data for twelve US-stock perpetuals. It does
            not scrape news or social media. When a post from a president or a CEO moves a stock, Slimon sees the
            move itself, at the close of the next five-minute candle, and every step of that is on the record.
          </SectionHeading>

          <div className="mt-12 grid gap-3 lg:grid-cols-3">
            {[
              {
                icon: Radar,
                title: "The source",
                body: "Tickers and 5-minute candles from Bitget's live venue, the real market, for 12 US-stock and index perps. The demo venue's own order book is read separately, because that is where orders fill.",
              },
              {
                icon: Clock,
                title: "How early",
                body: "Detectors run 15 seconds after every 5-minute candle closes, so a move is caught at the first close after it crosses a threshold: never more than about five minutes late. Each event records its candle time and the moment it was received, and each record carries the model's latency, so the delay is measured, not claimed.",
              },
              {
                icon: ShieldCheck,
                title: "How it is verified",
                body: "Closed candles only, never a half-formed one. Moves are compared against a baseline from the same US session. The model sees the whole cross-section to tell one stock's news from a market-wide move, and the gate refuses to open a position if the demo price strays more than 1.5% from the live market.",
              },
            ].map((c) => (
              <div key={c.title} className="rounded-xl border bg-card/40 p-6">
                <c.icon className="size-5 text-primary" />
                <p className="mt-4 font-medium">{c.title}</p>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.body}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 grid gap-6 rounded-xl border border-primary/25 bg-primary/[0.04] p-6 md:grid-cols-[auto_1fr] md:gap-8">
            <p className="font-display text-2xl leading-tight tracking-tight md:max-w-[14rem]">Why not race the tweets?</p>
            <div className="space-y-3 text-sm leading-relaxed text-muted-foreground">
              <p>
                Being first to a headline is a contest against firms with direct feeds and co-located servers, and a
                post can be misread, parodied or walked back within minutes. A price that has actually traded is the
                market&apos;s verdict on the news, whoever broke it.
              </p>
              <p>
                Stock perps trade around the clock, so news that lands at the weekend still moves them. Slimon keeps
                watching and logging, but opens nothing until the US pre-market session: thin weekend books are where
                reactions overshoot.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="gate" className="scroll-mt-10 border-t px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-[1fr_1.1fr] lg:items-end">
            <SectionHeading eyebrow="The risk gate" title={<>A prompt is not a control. <em className="text-primary">Code</em> is.</>}>
              The limits are never left to the model&apos;s good behaviour. They are enforced in plain code, and every
              limit lives in one committed config file whose hash is stamped on every log record.
            </SectionHeading>
            <figure className="min-w-0 rounded-xl border bg-card/50">
              <figcaption className="flex items-center justify-between border-b px-4 py-2.5 text-xs text-muted-foreground">
                <span>What a veto looks like</span>
                <span className="font-mono">smoke-test record</span>
              </figcaption>
              <div className="overflow-x-auto">
                <pre className="p-4 font-mono text-[12px] leading-relaxed text-foreground/85">{VETO_RECORD}</pre>
              </div>
            </figure>
          </div>

          <ul className="mt-14 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {RULES.map((r) => (
              <li key={r.name} className="rounded-xl border bg-card/40 p-5">
                <div className="flex items-baseline justify-between gap-3">
                  <code className="truncate font-mono text-[12.5px] text-foreground/90">{r.name}</code>
                  <span className="shrink-0 font-mono text-xs text-primary">{r.value}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{r.detail}</p>
              </li>
            ))}
          </ul>

          <div className="mt-6 grid gap-3 md:grid-cols-2">
            <div className="flex gap-4 rounded-xl border border-primary/25 bg-primary/[0.04] p-5">
              <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
              <div>
                <p className="font-medium">It also acts on its own</p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  A hard stop at −2.5%, enforced locally and preset on the exchange, and a 72-hour maximum hold close
                  positions without consulting the model.
                </p>
              </div>
            </div>
            <div className="flex gap-4 rounded-xl border p-5">
              <KeyRound className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
              <div>
                <p className="font-medium">A kill switch you can touch</p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  A <code className="font-mono text-foreground/85">STOP</code> file in the repository halts every new
                  position on the next tick. Closing still works.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="log" className="scroll-mt-10 border-t px-5 py-24 sm:px-8">
        <div className="mx-auto max-w-6xl">
          <SectionHeading eyebrow="The decision log" title="Nothing happens off the record">
            The log is the product&apos;s memory and its evidence. A reviewer can check any decision against the data
            that existed when it was made.
          </SectionHeading>
          <div className="mt-12 grid gap-3 md:grid-cols-3">
            {[
              {
                icon: Clock,
                title: "Timestamped on receipt",
                body: "Every event records when it was received and which candle it came from, so no decision can have been made with hindsight.",
              },
              {
                icon: Fingerprint,
                title: "Tied to its rules",
                body: "Each record carries the hash of the config it ran under, the model that answered, the request ID and the full gate verdict.",
              },
              {
                icon: KeyRound,
                title: "Safe to publish",
                body: "Credentials are scrubbed before any line is written. The log is committed to the repository as it grows.",
              },
            ].map((c) => (
              <div key={c.title} className="rounded-xl border bg-card/40 p-6">
                <c.icon className="size-5 text-primary" />
                <p className="mt-4 font-medium">{c.title}</p>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{c.body}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 overflow-x-auto rounded-xl border">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="bg-card/60 text-xs text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-medium">Mode</th>
                  <th className="px-5 py-3 font-medium">When</th>
                  <th className="px-5 py-3 font-medium">What happens</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                <tr>
                  <td className="px-5 py-3.5 font-mono text-[13px]">sim</td>
                  <td className="px-5 py-3.5 text-muted-foreground">No Bitget key</td>
                  <td className="px-5 py-3.5 text-muted-foreground">Local paper book priced off the demo venue&apos;s bid and ask.</td>
                </tr>
                <tr>
                  <td className="px-5 py-3.5 font-mono text-[13px]">dry_run</td>
                  <td className="px-5 py-3.5 text-muted-foreground">Key present, trading off</td>
                  <td className="px-5 py-3.5 text-muted-foreground">Reads the real demo account; orders are logged as would_submit, never sent.</td>
                </tr>
                <tr>
                  <td className="px-5 py-3.5 font-mono text-[13px]">live_demo</td>
                  <td className="px-5 py-3.5 text-muted-foreground">Key and ENABLE_TRADING=1</td>
                  <td className="px-5 py-3.5 text-muted-foreground">Orders go to Bitget&apos;s demo venue. No code path reaches live trading.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="border-t px-5 py-24 sm:px-8">
        <div className="relative mx-auto max-w-6xl overflow-hidden rounded-3xl border bg-card/40 px-6 py-16 text-center sm:px-12">
          <div
            aria-hidden
            className="pointer-events-none absolute -top-40 left-1/2 size-[28rem] -translate-x-1/2 rounded-full opacity-60 blur-3xl"
            style={{ background: "radial-gradient(circle, oklch(0.8 0.15 65 / 0.35), transparent 65%)" }}
          />
          <h2 className="relative font-display text-4xl tracking-tight sm:text-5xl">Read every decision it made</h2>
          <p className="relative mx-auto mt-4 max-w-xl text-muted-foreground">
            No keys, no setup. Open the log the agent has written and go through each decision, veto and fill, with
            the reasoning and the rules behind it.
          </p>
          <div className="relative mt-8 flex justify-center">
            <LaunchButton label="Launch App" />
          </div>
        </div>
      </section>

      <footer className="border-t px-5 py-10 sm:px-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>Slimon · Built for Bitget AI Base Camp Hackathon S2, Track 2: Agentic Trading.</p>
          <p>Paper trading on a demo venue. Not investment advice.</p>
        </div>
      </footer>
    </main>
  );
}
