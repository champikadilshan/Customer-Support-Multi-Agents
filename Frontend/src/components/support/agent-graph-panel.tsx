"use client"

import { useEffect, useRef, useState } from "react"
import { Bot, ChevronDown, ChevronUp, Play } from "lucide-react"

import { cn } from "@/lib/utils"
import { type AgentGraphState, type AgentNodeId } from "@/lib/agent-graph"
import { AgentFlowCanvas } from "@/components/support/agent-flow-canvas"
import { Button } from "@/components/ui/button"

type AgentGraphPanelProps = {
  graph: AgentGraphState
  isLive: boolean
  hideHeader?: boolean
  sessionId?: string | null
  onReplay?: (sessionId: string) => Promise<void>
}

const BADGE_STYLES: Record<string, string> = {
  orchestrator_dispatch: "bg-purple-500/15 text-purple-700 dark:text-purple-300",
  agent_start: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  agent_end: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  agent_handoff: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  tool_start: "bg-teal-500/15 text-teal-700 dark:text-teal-300",
  tool_end: "bg-teal-500/15 text-teal-700 dark:text-teal-300",
  hitl_requested: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  hitl_resumed: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  error: "bg-destructive/15 text-destructive",
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

function eventBadgeLabel(eventType?: string) {
  if (!eventType) return "event"
  return eventType.replace(/_/g, " ")
}

export function AgentGraphPanel({
  graph,
  isLive,
  hideHeader = false,
  sessionId,
  onReplay,
}: AgentGraphPanelProps) {
  const [highlightNodeId, setHighlightNodeId] = useState<AgentNodeId | null>(null)
  const [isReplaying, setIsReplaying] = useState(false)
  const [isEventLogOpen, setIsEventLogOpen] = useState(true)
  const logScrollRef = useRef<HTMLDivElement>(null)

  const activeNodes = Object.values(graph.nodes).filter(
    (node) => node.status === "active" || node.status === "waiting"
  )

  useEffect(() => {
    if (!isEventLogOpen) return
    const container = logScrollRef.current
    if (!container) return
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" })
  }, [graph.activities.length, isEventLogOpen])

  const handleReplay = async () => {
    if (!sessionId || !onReplay || isReplaying) return
    setIsReplaying(true)
    try {
      await onReplay(sessionId)
    } finally {
      setIsReplaying(false)
    }
  }

  const handleActivityClick = (nodeId?: AgentNodeId) => {
    if (!nodeId) return
    setHighlightNodeId(nodeId)
    window.setTimeout(() => setHighlightNodeId(null), 1200)
  }

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
        <div className="flex shrink-0 items-center gap-2">
          {sessionId && onReplay ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 px-2 text-[11px]"
              onClick={() => void handleReplay()}
              disabled={isReplaying}
            >
              <Play className="h-3 w-3" />
              {isReplaying ? "Replaying…" : "Replay"}
            </Button>
          ) : null}
          {graph.lastEventAt ? (
            <span className="text-[11px] text-muted-foreground">
              Updated {formatTraceTime(graph.lastEventAt)}
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
        <AgentFlowCanvas
          graph={graph}
          highlightNodeId={highlightNodeId}
          className={cn(
            "min-h-0 basis-0 transition-[flex-grow]",
            isEventLogOpen ? "flex-[3]" : "flex-1"
          )}
        />

        <div
          className={cn(
            "flex flex-col overflow-hidden rounded-xl border bg-background/70 transition-all",
            isEventLogOpen ? "min-h-0 flex-[2] basis-0" : "shrink-0"
          )}
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
            <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Event log
              {!isEventLogOpen && graph.activities.length > 0 ? (
                <span className="ml-1.5 font-normal normal-case text-muted-foreground/80">
                  ({graph.activities.length})
                </span>
              ) : null}
            </p>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0 text-muted-foreground"
              onClick={() => setIsEventLogOpen((open) => !open)}
              aria-label={isEventLogOpen ? "Collapse event log" : "Expand event log"}
              aria-expanded={isEventLogOpen}
            >
              {isEventLogOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronUp className="h-4 w-4" />
              )}
            </Button>
          </div>

          {isEventLogOpen ? (
            <div
              ref={logScrollRef}
              className="scrollbar-hidden min-h-0 flex-1 overflow-y-auto p-2"
            >
              {graph.activities.length > 0 ? (
                <ul className="space-y-1.5 pb-1">
                  {graph.activities.map((activity) => (
                    <li key={activity.id}>
                      <button
                        type="button"
                        onClick={() => handleActivityClick(activity.highlightNodeId)}
                        className={cn(
                          "w-full rounded-md border border-border/60 bg-muted/30 px-2.5 py-1.5 text-left text-sm transition-colors",
                          activity.highlightNodeId &&
                            "hover:border-foreground/25 hover:bg-muted/50"
                        )}
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {formatActivityTime(activity.timestamp)}
                          </span>
                          {activity.eventType ? (
                            <span
                              className={cn(
                                "rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide",
                                BADGE_STYLES[activity.eventType] ??
                                  "bg-muted text-muted-foreground"
                              )}
                            >
                              {eventBadgeLabel(activity.eventType)}
                            </span>
                          ) : null}
                          <span className="text-xs text-foreground">
                            {activity.agent ?? activity.tool ?? activity.message}
                            {activity.durationMs != null
                              ? ` · ${activity.durationMs}ms`
                              : null}
                          </span>
                        </div>
                        <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground">
                          {activity.message}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-1 text-xs leading-snug text-muted-foreground">
                  Trace events appear here as agents route, call tools, and hand off.
                </p>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
