import { cn } from "@/lib/utils";

/**
 * Stand-in for BlackHoleHeroSection until the full component is saved to
 * components/ui/blackhole-hero-section.tsx. It keeps the same contract (a
 * full-bleed dark section, the hole framed high and right, a left scrim for
 * text, children on top) so replacing it is a one-line change in hero.tsx.
 * This is a static CSS sketch, not the ray-traced render.
 */
export function HeroBackdrop({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <section className={cn("relative isolate overflow-hidden bg-background", className)}>
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute top-[40%] left-[72%] -translate-x-1/2 -translate-y-1/2 -rotate-[9deg]">
          {/* far side of the disc, lensed up and over the shadow */}
          <div
            className="absolute top-1/2 left-1/2 size-[min(62vmin,640px)] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-80 blur-[2px]"
            style={{
              background:
                "radial-gradient(circle, transparent 38%, oklch(0.85 0.12 75 / 0.9) 39.5%, oklch(0.7 0.16 50 / 0.45) 44%, transparent 58%)",
            }}
          />
          {/* the disc itself, edge-on */}
          <div
            className="absolute top-1/2 left-1/2 h-[min(7vmin,72px)] w-[min(150vmin,1500px)] -translate-x-1/2 -translate-y-1/2 rounded-[100%] blur-[6px]"
            style={{
              background:
                "radial-gradient(ellipse at center, oklch(0.95 0.08 85) 0%, oklch(0.8 0.15 65) 18%, oklch(0.55 0.16 40 / 0.7) 42%, transparent 70%)",
            }}
          />
          {/* shadow */}
          <div
            className="absolute top-1/2 left-1/2 size-[min(26vmin,270px)] -translate-x-1/2 -translate-y-1/2 rounded-full bg-black"
            style={{ boxShadow: "0 0 0 1.5px oklch(0.95 0.08 85 / 0.9), 0 0 28px 6px oklch(0.8 0.15 65 / 0.45)" }}
          />
          {/* near side of the disc crossing in front of the shadow */}
          <div
            className="absolute top-1/2 left-1/2 h-[min(4vmin,40px)] w-[min(120vmin,1200px)] -translate-x-1/2 -translate-y-[35%] rounded-[100%] blur-[4px]"
            style={{
              background:
                "radial-gradient(ellipse at center, oklch(0.97 0.06 88) 0%, oklch(0.82 0.15 68) 22%, oklch(0.55 0.16 40 / 0.6) 48%, transparent 72%)",
              clipPath: "inset(45% 0 0 0)",
            }}
          />
        </div>
        {/* scrim so the copy on the left stays readable */}
        <div className="absolute inset-0 bg-gradient-to-r from-background via-background/75 to-transparent md:via-background/55" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-background" />
      </div>
      {children}
    </section>
  );
}
