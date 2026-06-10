"use client"

import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  formatHitlCategory,
  formatHitlPriority,
  priorityBadgeVariant,
  type HitlRequest,
} from "@/lib/hitl"
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

function TicketPreviewDetails({ preview }: { preview: HitlRequest["ticket_preview"] }) {
  const category = formatHitlCategory(preview.category)
  const priority = formatHitlPriority(preview.priority)

  if (!preview.title && !preview.description && !category && !priority) {
    return null
  }

  return (
    <div className="mt-3 space-y-2.5 rounded-md border border-border/60 bg-background/80 px-3 py-2.5">
      {preview.title ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Title
          </p>
          <p className="mt-0.5 text-sm font-medium leading-snug text-foreground">
            {preview.title}
          </p>
        </div>
      ) : null}

      {preview.description ? (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Reason
          </p>
          <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
            {preview.description}
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {preview.customer_id ? (
          <span className="text-xs text-muted-foreground">
            Customer{" "}
            <span className="font-medium text-foreground">{preview.customer_id}</span>
          </span>
        ) : null}
        {category ? <Badge variant="outline">{category}</Badge> : null}
        {priority ? (
          <Badge variant={priorityBadgeVariant(priority)}>{priority}</Badge>
        ) : null}
      </div>
    </div>
  )
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

      <TicketPreviewDetails preview={request.ticket_preview} />

      <p className="mt-3 text-sm font-light leading-relaxed text-muted-foreground">
        {prompt}
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
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
