"use client"

import { useState } from "react"
import { GitBranch, Ticket } from "lucide-react"

import { cn } from "@/lib/utils"
import { type AgentGraphState } from "@/lib/agent-graph"
import { AgentGraphPanel } from "@/components/support/agent-graph-panel"
import { TicketsPanel } from "@/components/support/tickets-panel"
import { Button } from "@/components/ui/button"

type SidebarView = "tickets" | "graph"

type RightSidebarProps = {
  graph: AgentGraphState
  isGraphLive: boolean
}

export function RightSidebar({ graph, isGraphLive }: RightSidebarProps) {
  const [view, setView] = useState<SidebarView>("tickets")

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 inline-flex w-full rounded-lg border bg-muted/30 p-1">
        <Button
          type="button"
          size="sm"
          variant={view === "tickets" ? "default" : "ghost"}
          className={cn("flex-1 gap-2", view === "tickets" && "shadow-sm")}
          onClick={() => setView("tickets")}
        >
          <Ticket className="h-4 w-4" />
          Tickets
        </Button>
        <Button
          type="button"
          size="sm"
          variant={view === "graph" ? "default" : "ghost"}
          className={cn("flex-1 gap-2", view === "graph" && "shadow-sm")}
          onClick={() => setView("graph")}
        >
          <GitBranch className="h-4 w-4" />
          Agent Flow
        </Button>
      </div>

      <div className="min-h-0 flex-1">
        {view === "tickets" ? (
          <TicketsPanel embedded />
        ) : (
          <AgentGraphPanel graph={graph} isLive={isGraphLive} />
        )}
      </div>
    </div>
  )
}
