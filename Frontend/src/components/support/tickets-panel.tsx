"use client"

import { useState } from "react"
import { RefreshCw } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  formatCategoryLabel,
  formatStatusLabel,
  formatTicketDate,
  type Ticket,
  type TicketStatus,
} from "@/lib/tickets"
import { useTickets } from "@/hooks/use-tickets"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

function statusVariant(status: TicketStatus) {
  return status
}

function priorityVariant(priority: string | null) {
  if (!priority) return "muted" as const
  if (priority === "critical") return "critical" as const
  if (priority === "high") return "high" as const
  if (priority === "medium") return "medium" as const
  return "low" as const
}

function TicketCard({ ticket }: { ticket: Ticket }) {
  const category = formatCategoryLabel(ticket.category)

  return (
    <article className="rounded-lg bg-muted/50 p-3 transition-colors hover:bg-muted">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">
            Ticket #{ticket.id}
          </p>
          <h3 className="mt-1 text-sm font-semibold leading-snug tracking-tight">
            {ticket.title}
          </h3>
        </div>
        <Badge variant={statusVariant(ticket.status)}>
          {formatStatusLabel(ticket.status)}
        </Badge>
      </div>

      <p className="mt-2 line-clamp-2 text-sm font-light leading-relaxed text-muted-foreground">
        {ticket.description}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {category ? <Badge variant="outline">{category}</Badge> : null}
        {ticket.priority ? (
          <Badge variant={priorityVariant(ticket.priority)}>
            {ticket.priority}
          </Badge>
        ) : null}
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{ticket.customer_id}</span>
        <span>{formatTicketDate(ticket.created_at)}</span>
      </div>

      {ticket.assigned_to ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Assigned to{" "}
          <span className="font-medium text-foreground">
            {ticket.assigned_to}
          </span>
        </p>
      ) : null}
    </article>
  )
}

function TicketsSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 3 }).map((_, index) => (
        <div
          key={index}
          className="animate-pulse rounded-lg bg-muted/40 p-3"
        >
          <div className="h-3 w-16 rounded bg-muted" />
          <div className="mt-3 h-4 w-4/5 rounded bg-muted" />
          <div className="mt-2 h-3 w-full rounded bg-muted" />
          <div className="mt-2 h-3 w-2/3 rounded bg-muted" />
        </div>
      ))}
    </div>
  )
}

export function TicketsPanel({ embedded = false }: { embedded?: boolean }) {
  const { tickets, isLoading, error, refresh } = useTickets()
  const [isRefreshing, setIsRefreshing] = useState(false)

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await refresh()
    setIsRefreshing(false)
  }

  const content = (
    <>
      <div className="flex items-start justify-between gap-3 pb-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Support Tickets
          </h2>
          <p className="mt-1 text-sm font-light text-muted-foreground">
            Tickets created through customer support
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          aria-label="Refresh tickets"
          onClick={() => void handleRefresh()}
          disabled={isRefreshing}
        >
          <RefreshCw
            className={cn("h-4 w-4", isRefreshing && "animate-spin")}
          />
        </Button>
      </div>

      <div className="scrollbar-hidden flex-1 overflow-y-auto">
        {isLoading ? <TicketsSkeleton /> : null}

        {!isLoading && error ? (
          <div className="py-8 text-center">
            <p className="text-sm font-light text-muted-foreground">{error}</p>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-4"
              onClick={() => void handleRefresh()}
            >
              Try again
            </Button>
          </div>
        ) : null}

        {!isLoading && !error && tickets.length === 0 ? (
          <div className="py-8 text-center">
            <p className="text-sm font-medium">No tickets yet</p>
            <p className="mt-1 text-sm font-light text-muted-foreground">
              Tickets raised during support conversations will appear here.
            </p>
          </div>
        ) : null}

        {!isLoading && !error && tickets.length > 0 ? (
          <div className="space-y-3">
            {tickets.map((ticket) => (
              <TicketCard key={ticket.id} ticket={ticket} />
            ))}
          </div>
        ) : null}
      </div>
    </>
  )

  if (embedded) {
    return <div className="flex h-full flex-col overflow-hidden">{content}</div>
  }

  return (
    <div className="sticky top-16 flex max-h-[calc(100vh-8rem-32px)] flex-col overflow-hidden">
      {content}
    </div>
  )
}
