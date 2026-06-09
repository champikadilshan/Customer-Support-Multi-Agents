"use client"

import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react"

import { cn } from "@/lib/utils"
import { type HitlRequest } from "@/lib/hitl"
import { Button } from "@/components/ui/button"

type HitlConfirmationCardProps = {
  request: HitlRequest
  response?: "yes" | "no"
  isResponding?: boolean
  disabled?: boolean
  onRespond: (response: "yes" | "no") => void
  className?: string
}

export function HitlConfirmationCard({
  request,
  response,
  isResponding = false,
  disabled = false,
  onRespond,
  className,
}: HitlConfirmationCardProps) {
  const yesLabel = request.options[0] ?? "Yes, create ticket"
  const noLabel = request.options[1] ?? "No, cancel"
  const prompt =
    request.question.split("\n\n").at(-1) ??
    "Shall I go ahead and create this support ticket for you?"

  if (response) {
    const approved = response === "yes"

    return (
      <div
        className={cn(
          "w-full max-w-md rounded-lg border border-border/60 bg-muted/40 px-4 py-3",
          className
        )}
      >
        <div className="flex items-center gap-2 text-sm">
          {approved ? (
            <CheckCircle2 className="h-4 w-4 text-foreground" />
          ) : (
            <XCircle className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-muted-foreground">
            {approved ? yesLabel : noLabel}
            {isResponding ? " — processing..." : ""}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div
      className={cn(
        "w-full max-w-md rounded-lg border border-border/60 bg-muted/50 p-4 duration-300 animate-in fade-in-0",
        className
      )}
    >
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-foreground" />
        <p className="text-sm font-semibold tracking-tight">
          Confirm ticket creation
        </p>
      </div>

      <p className="mt-1.5 text-sm font-light leading-relaxed text-muted-foreground">
        {prompt}
      </p>

      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={disabled}
          onClick={() => onRespond("yes")}
        >
          {yesLabel}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          onClick={() => onRespond("no")}
        >
          {noLabel}
        </Button>
      </div>
    </div>
  )
}
