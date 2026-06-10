import { cn } from "@/lib/utils"

const SPARKLES = [
  { top: "18%", left: "62%", delay: "0s", size: "h-1 w-1" },
  { top: "42%", left: "28%", delay: "0.8s", size: "h-0.5 w-0.5" },
  { top: "68%", left: "58%", delay: "1.4s", size: "h-1 w-1" },
  { top: "55%", left: "72%", delay: "2s", size: "h-0.5 w-0.5" },
  { top: "30%", left: "44%", delay: "1.1s", size: "h-0.5 w-0.5" },
]

export function ChatEmptyState() {
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-2">
      <div className="relative mb-5 flex h-32 w-32 items-center justify-center">
        <div
          aria-hidden
          className="absolute inset-0 animate-orb-glow rounded-full bg-gradient-to-br from-foreground/10 via-muted/30 to-foreground/5 blur-2xl dark:from-foreground/15 dark:via-muted/20 dark:to-foreground/5"
        />

        <div className="absolute inset-2 animate-orb-float rounded-full">
          <div
            aria-hidden
            className="absolute inset-0 overflow-hidden rounded-full shadow-[0_8px_32px_rgba(0,0,0,0.08)] dark:shadow-[0_8px_32px_rgba(0,0,0,0.35)]"
          >
            <div className="absolute inset-0 rounded-full bg-gradient-to-br from-white via-zinc-100 to-zinc-200/90 dark:from-zinc-600 dark:via-zinc-700 dark:to-zinc-800" />
            <div className="absolute inset-0 rounded-full bg-gradient-to-tr from-rose-100/50 via-transparent to-violet-100/40 dark:from-rose-300/10 dark:to-violet-300/10" />
            <div
              className="absolute -inset-1/2 animate-orb-shimmer opacity-60"
              style={{
                background:
                  "conic-gradient(from 0deg, transparent 0%, rgba(255,255,255,0.45) 18%, transparent 36%, rgba(255,255,255,0.2) 54%, transparent 72%)",
              }}
            />
            <div className="absolute inset-[18%] rounded-full bg-gradient-to-br from-white/70 to-transparent blur-sm dark:from-white/10" />
            <div className="absolute inset-0 rounded-full border border-white/60 dark:border-white/10" />
          </div>

          {SPARKLES.map((sparkle) => (
            <span
              key={`${sparkle.top}-${sparkle.left}`}
              aria-hidden
              className={cn(
                "absolute animate-sparkle rounded-full bg-white/90 dark:bg-white/70",
                sparkle.size
              )}
              style={{
                top: sparkle.top,
                left: sparkle.left,
                animationDelay: sparkle.delay,
              }}
            />
          ))}
        </div>
      </div>

      <h2 className="text-center text-lg font-semibold tracking-tight">
        How can we help you today?
      </h2>
      <p className="mt-1.5 max-w-[220px] text-center text-sm font-light text-muted-foreground">
        Ask about billing, sales, or complaints
      </p>
    </div>
  )
}
