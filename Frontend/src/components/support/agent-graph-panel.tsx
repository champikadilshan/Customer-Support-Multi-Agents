"use client"

import { cn } from "@/lib/utils"
import {
  AGENT_NODES,
  getEdgeStatus,
  type AgentGraphState,
  type AgentNodeId,
  type EdgeStatus,
  type NodeStatus,
} from "@/lib/agent-graph"

type AgentGraphPanelProps = {
  graph: AgentGraphState
  isLive: boolean
}

function statusStyles(status: NodeStatus) {
  switch (status) {
    case "active":
      return "border-foreground bg-foreground text-background shadow-sm"
    case "completed":
      return "border-foreground/30 bg-muted text-foreground"
    case "waiting":
      return "border-amber-500/50 bg-amber-50 text-foreground dark:bg-amber-950/20"
    case "error":
      return "border-destructive/50 bg-destructive/10 text-foreground"
    default:
      return "border-border/60 bg-muted/30 text-muted-foreground"
  }
}

function statusLabel(status: NodeStatus) {
  switch (status) {
    case "active":
      return "Running"
    case "completed":
      return "Done"
    case "waiting":
      return "Waiting"
    case "error":
      return "Error"
    default:
      return "Idle"
  }
}

function GraphNode({
  nodeId,
  graph,
}: {
  nodeId: AgentNodeId
  graph: AgentGraphState
}) {
  const node = graph.nodes[nodeId]
  const meta = AGENT_NODES[nodeId]
  const isRouted = graph.routedAgent === nodeId
  const isActive = node.status === "active" || node.status === "waiting"

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5 transition-all duration-300",
        statusStyles(node.status),
        isRouted && node.status === "idle" && "opacity-40",
        !isRouted &&
          graph.routedAgent &&
          ["billing", "complaint", "sales"].includes(nodeId) &&
          node.status === "idle" &&
          "opacity-30"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-semibold tracking-tight">{meta.label}</p>
          <p
            className={cn(
              "mt-0.5 text-[11px] leading-snug",
              node.status === "active" || node.status === "waiting"
                ? "text-inherit/80"
                : "text-muted-foreground"
            )}
          >
            {node.detail ?? meta.description}
          </p>
        </div>
        <span
          className={cn(
            "mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
            node.status === "active" && "bg-background/15 text-inherit",
            node.status === "completed" && "bg-foreground/10 text-foreground",
            node.status === "waiting" && "bg-amber-500/15 text-amber-700 dark:text-amber-300",
            node.status === "error" && "bg-destructive/15 text-destructive",
            node.status === "idle" && "bg-muted text-muted-foreground"
          )}
        >
          {isActive ? (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
          ) : null}
          {statusLabel(node.status)}
        </span>
      </div>
    </div>
  )
}

function GraphConnector({ status }: { status: EdgeStatus }) {
  return (
    <div className="flex justify-center py-1">
      <div
        className={cn(
          "h-5 w-px transition-colors duration-300",
          status === "active" && "bg-foreground",
          status === "completed" && "bg-foreground/40",
          status === "idle" && "bg-border"
        )}
      />
    </div>
  )
}

function formatActivityTime(timestamp: number) {
  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

export function AgentGraphPanel({ graph, isLive }: AgentGraphPanelProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Agent Flow</h2>
            <p className="mt-1 text-sm font-light text-muted-foreground">
              Live routing and backend activity
            </p>
          </div>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
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
            {isLive ? "Live" : "Idle"}
          </span>
        </div>
      </div>

      <div className="scrollbar-hidden flex-1 overflow-y-auto pr-1">
        <div className="space-y-1">
          <GraphNode nodeId="intent_detector" graph={graph} />

          <GraphConnector
            status={
              graph.routedAgent
                ? getEdgeStatus(graph, "intent_detector", graph.routedAgent)
                : "idle"
            }
          />

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <GraphNode nodeId="billing" graph={graph} />
            <GraphNode nodeId="complaint" graph={graph} />
            <GraphNode nodeId="sales" graph={graph} />
          </div>

          {graph.showComplaintFlow ? (
            <>
              <GraphConnector
                status={getEdgeStatus(graph, "complaint", "tools")}
              />
              <GraphNode nodeId="tools" graph={graph} />
              <GraphConnector status={getEdgeStatus(graph, "tools", "hitl")} />
              <GraphNode nodeId="hitl" graph={graph} />
              <GraphConnector
                status={getEdgeStatus(graph, "hitl", "ticket_service")}
              />
              <GraphNode nodeId="ticket_service" graph={graph} />
            </>
          ) : null}
        </div>

        <div className="mt-5 border-t pt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Activity
          </p>
          {graph.activities.length > 0 ? (
            <ul className="mt-3 space-y-2">
              {graph.activities.map((activity) => (
                <li
                  key={activity.id}
                  className="rounded-lg bg-muted/40 px-3 py-2 text-sm"
                >
                  <p className="leading-snug text-foreground">
                    {activity.message}
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {formatActivityTime(activity.timestamp)}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm font-light text-muted-foreground">
              Send a message to watch agents route and communicate in real time.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
