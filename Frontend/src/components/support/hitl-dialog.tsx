"use client"

import { Button } from "@/components/ui/button"
import { type HitlRequest } from "@/hooks/use-support-chat"

type HitlDialogProps = {
  request: HitlRequest
  onRespond: (response: "yes" | "no") => void
  disabled?: boolean
}

export function HitlDialog({ request, onRespond, disabled }: HitlDialogProps) {
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      <p className="mb-3 text-sm font-medium">Approval required</p>
      <pre className="mb-4 whitespace-pre-wrap text-sm text-muted-foreground">
        {request.question}
      </pre>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          disabled={disabled}
          onClick={() => onRespond("yes")}
        >
          Yes, raise it
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => onRespond("no")}
        >
          No, skip it
        </Button>
      </div>
    </div>
  )
}
