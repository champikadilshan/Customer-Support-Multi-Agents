import { cn } from "@/lib/utils"

interface AgentActivityIndicatorProps {
  message: string
  className?: string
}

export function AgentActivityIndicator({
  message,
  className,
}: AgentActivityIndicatorProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 text-sm text-muted-foreground",
        className
      )}
    >
      <span className="relative flex h-2.5 w-2.5 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/50 opacity-75" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary/70" />
      </span>

      <span className="min-w-0">{message}</span>

      <span className="inline-flex shrink-0 gap-0.5 pb-0.5">
        <span className="animate-typing-dot-bounce">.</span>
        <span className="animate-typing-dot-bounce [animation-delay:120ms]">
          .
        </span>
        <span className="animate-typing-dot-bounce [animation-delay:240ms]">
          .
        </span>
      </span>
    </div>
  )
}
