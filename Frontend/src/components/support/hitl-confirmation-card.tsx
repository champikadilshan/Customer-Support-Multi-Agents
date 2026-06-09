"use client"

import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react"

import { cn } from "@/lib/utils"
import { type HitlRequest } from "@/lib/hitl"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

type HitlConfirmationCardProps = {
  request: HitlRequest
  response?: "yes" | "no"
  isResponding?: boolean
  disabled?: boolean
  onRespond: (response: "yes" | "no") => void
  className?: string
}

function priorityVariant(priority?: string) {
  if (!priority) return "muted" as const
  if (priority === "critical") return "critical" as const
  if (priority === "high") return "high" as const
  if (priority === "medium") return "medium" as const
  return "low" as const
}

export function HitlConfirmationCard({
  request,
  response,
  isResponding = false,
  disabled = false,
  onRespond,
  className,
}: HitlConfirmationCardProps) {
  const { ticket_preview: preview } = request
  const yesLabel = request.options[0] ?? "Yes, create ticket"
  const noLabel = request.options[1] ?? "No, cancel"

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
        "w-full max-w-md rounded-lg border border-border/60 bg-muted/50 p-4 duration-300 animate-in fade-in-0 slide-in-from-left",
        className
      )}
    >
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-foreground" />
        <p className="text-sm font-semibold tracking-tight">
          Confirm ticket creation
        </p>
      </div>

      {preview.title ? (
        <h4 className="mt-3 text-sm font-semibold leading-snug">
          {preview.title}
        </h4>
      ) : null}

      <div className="mt-2 flex flex-wrap gap-2">
        {preview.category ? (
          <Badge variant="outline">{preview.category.replace(/_/g, " ")}</Badge>
        ) : null}
        {preview.priority ? (
          <Badge variant={priorityVariant(preview.priority)}>
            {preview.priority}
          </Badge>
        ) : null}
      </div>

      <p className="mt-3 text-sm font-light leading-relaxed text-muted-foreground">
        {request.question.split("\n\n").at(-1) ??
          "Shall I go ahead and create this support ticket for you?"}
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
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
