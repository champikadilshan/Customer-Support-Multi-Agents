"use client"

import { useState } from "react"
import { RefreshCw } from "lucide-react"

import { cn } from "@/lib/utils"
import { type AgentGraphState } from "@/lib/agent-graph"
import { AgentGraphPanel } from "@/components/support/agent-graph-panel"
import { TicketsPanel } from "@/components/support/tickets-panel"
import {
  SidebarViewToggle,
  type SidebarView,
} from "@/components/support/sidebar-view-toggle"
import { Button } from "@/components/ui/button"
import { refreshTicketsPanel } from "@/hooks/use-tickets"

type RightSidebarProps = {
  graph: AgentGraphState
  isGraphLive: boolean
}

export function RightSidebar({ graph, isGraphLive }: RightSidebarProps) {
  const [view, setView] = useState<SidebarView>("tickets")
  const [isRefreshing, setIsRefreshing] = useState(false)

  const handleRefresh = () => {
    setIsRefreshing(true)
    refreshTicketsPanel()
    window.setTimeout(() => setIsRefreshing(false), 600)
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="mb-3 flex shrink-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold tracking-tight">
            {view === "tickets" ? "Support Tickets" : "Agent Flow"}
          </h2>
          <p className="mt-1 text-sm font-light text-muted-foreground">
            {view === "tickets"
              ? "Tickets created through customer support"
              : "Live node graph with real-time trace data flow"}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {view === "tickets" ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label="Refresh tickets"
              onClick={handleRefresh}
              disabled={isRefreshing}
            >
              <RefreshCw
                className={cn("h-4 w-4", isRefreshing && "animate-spin")}
              />
            </Button>
          ) : null}
          <SidebarViewToggle value={view} onChange={setView} />
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {view === "tickets" ? (
          <TicketsPanel embedded hideHeader />
        ) : (
          <AgentGraphPanel graph={graph} isLive={isGraphLive} hideHeader />
        )}
      </div>
    </div>
  )
}
