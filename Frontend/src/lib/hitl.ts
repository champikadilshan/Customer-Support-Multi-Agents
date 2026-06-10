export type TicketPreview = {
  title?: string
  description?: string
  customer_id?: string
  category?: string
  priority?: string
  staged?: boolean
}

export type HitlRequest = {
  request_id: string
  question: string
  ticket_preview: TicketPreview
  options: string[]
}

/** Client-side HITL gate state (from POST /chat response). */
export type HitlPending = {
  request_id: string
  ticket_preview: TicketPreview
  hitl_question: string
  hitl_options: string[]
}

export function hitlPendingToRequest(pending: HitlPending): HitlRequest {
  return {
    request_id: pending.request_id,
    question: pending.hitl_question,
    ticket_preview: pending.ticket_preview,
    options: pending.hitl_options,
  }
}

export function formatHitlCategory(category?: string) {
  if (!category) return null
  return category.replace(/_/g, " ")
}

export function formatHitlPriority(priority?: string) {
  if (!priority) return null
  return priority
}

export function priorityBadgeVariant(
  priority?: string
): "critical" | "high" | "medium" | "low" | "muted" {
  if (!priority) return "muted"
  if (priority === "critical") return "critical"
  if (priority === "high") return "high"
  if (priority === "medium") return "medium"
  return "low"
}
