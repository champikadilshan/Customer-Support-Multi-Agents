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
