"use client"

import { Bot } from "lucide-react"

import { cn } from "@/lib/utils"
import { type AgentGraphState } from "@/lib/agent-graph"
import { AgentFlowCanvas } from "@/components/support/agent-flow-canvas"

type AgentGraphPanelProps = {
  graph: AgentGraphState
  isLive: boolean
  hideHeader?: boolean
}

function formatActivityTime(timestamp: number) {
  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function formatTraceTime(timestamp: number | null) {
  if (!timestamp) return null
  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

function TraceStatusChip({
  graph,
  isLive,
}: {
  graph: AgentGraphState
  isLive: boolean
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        isLive
          ? "border-foreground/20 bg-muted text-foreground"
          : "border-border text-muted-foreground"
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          isLive ? "animate-pulse bg-foreground" : "bg-muted-foreground"
        )}
      />
      {graph.traceConnected ? (isLive ? "Live trace" : "Connected") : "Waiting"}
    </span>
  )
}

export function AgentGraphPanel({
  graph,
  isLive,
  hideHeader = false,
}: AgentGraphPanelProps) {
  const activeNodes = Object.values(graph.nodes).filter(
    (node) => node.status === "active" || node.status === "waiting"
  )

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {!hideHeader ? (
        <div className="shrink-0 pb-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">Agent Flow</h2>
              <p className="mt-1 text-sm font-light text-muted-foreground">
                Live node graph with real-time trace data flow
              </p>
            </div>
            <TraceStatusChip graph={graph} isLive={isLive} />
          </div>
        </div>
      ) : null}

      <div className="mb-3 flex shrink-0 items-center justify-between gap-2 rounded-xl border bg-background/70 px-3 py-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Bot className="h-4 w-4 shrink-0" />
          <span className="min-w-0">
            {activeNodes.length > 0
              ? `${activeNodes.length} active node${activeNodes.length === 1 ? "" : "s"}`
              : "All nodes idle — send a message to start the flow"}
          </span>
          {hideHeader ? (
            <TraceStatusChip graph={graph} isLive={isLive} />
          ) : null}
        </div>
        {graph.lastEventAt ? (
          <span className="shrink-0 text-[11px] text-muted-foreground">
            Updated {formatTraceTime(graph.lastEventAt)}
          </span>
        ) : null}
      </div>

      <AgentFlowCanvas graph={graph} className="min-h-[480px] flex-1" />

      <div className="mt-3 shrink-0 border-t pt-2">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Activity
        </p>
        <div className="scrollbar-hidden mt-1 h-[160px] overflow-y-auto">
          {graph.activities.length > 0 ? (
            <ul className="space-y-1.5">
              {graph.activities.map((activity) => (
                <li
                  key={activity.id}
                  className="rounded-md border border-border/60 bg-muted/30 px-2.5 py-1.5 text-sm"
                >
                  <p className="leading-snug text-foreground">{activity.message}</p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">
                    {formatActivityTime(activity.timestamp)}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs leading-snug text-muted-foreground">
              Trace events appear here as agents route, call tools, and hand off.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
