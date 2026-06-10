export type TicketStatus = "open" | "in_progress" | "resolved" | "closed"

export type Ticket = {
  id: number
  title: string
  description: string
  customer_id: string
  status: TicketStatus
  category: string | null
  priority: string | null
  assigned_to: string | null
  created_at: string
  updated_at: string
}

export async function fetchTickets(): Promise<Ticket[]> {
  const response = await fetch("/api/tickets", { cache: "no-store" })

  if (!response.ok) {
    throw new Error("Failed to load tickets")
  }

  return response.json()
}

export function formatTicketDate(value: string) {
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

export function formatStatusLabel(status: TicketStatus) {
  return status.replace("_", " ")
}

export function formatCategoryLabel(category: string | null) {
  if (!category) return null
  return category.replace(/_/g, " ")
}
