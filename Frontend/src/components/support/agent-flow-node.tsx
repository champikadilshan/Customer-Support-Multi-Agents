"use client"

import { memo } from "react"
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react"
import {
  CreditCard,
  Database,
  GitBranch,
  Headphones,
  MessageSquareWarning,
  Network,
  Server,
  ShieldCheck,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { formatToolLabel } from "@/lib/agent-tools"
import { AGENT_NODES, type AgentNodeId, type NodeStatus } from "@/lib/agent-graph"
import type { AgentFlowNodeData } from "@/lib/agent-flow-elements"
import type { HealthStatus } from "@/hooks/use-agent-health"

const NODE_ICONS: Record<
  AgentNodeId,
  React.ComponentType<{ className?: string }>
> = {
  intent_detector: GitBranch,
  billing: CreditCard,
  complaint: MessageSquareWarning,
  sales: Headphones,
  hitl: ShieldCheck,
  billing_db: Database,
  sales_mcp: Network,
  product_db: Database,
  ticket_api: Server,
  ticket_db: Database,
}

function healthDotClass(health?: HealthStatus) {
  switch (health) {
    case "healthy":
      return "bg-emerald-500"
    case "down":
      return "bg-destructive"
    default:
      return "bg-muted-foreground/50"
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

const handleClass =
  "!h-2 !w-2 !min-h-0 !min-w-0 !border-0 !bg-transparent !opacity-0"

function FlowNodeHandles() {
  return (
    <>
      <Handle type="target" position={Position.Top} id="top" className={handleClass} />
      <Handle type="source" position={Position.Bottom} id="bottom" className={handleClass} />
      <Handle type="target" position={Position.Left} id="left" className={handleClass} />
      <Handle type="source" position={Position.Right} id="right" className={handleClass} />
      <Handle type="source" position={Position.Left} id="source-left" className={handleClass} />
      <Handle type="target" position={Position.Right} id="target-right" className={handleClass} />
    </>
  )
}

function AgentFlowNodeComponent({ data }: NodeProps<Node<AgentFlowNodeData>>) {
  const meta = AGENT_NODES[data.nodeId]
  const Icon = NODE_ICONS[data.nodeId]
  const isActive = data.status === "active" || data.status === "waiting"
  const isInfra = data.kind === "infra"
  const detailText = data.runningTool
    ? formatToolLabel(data.runningTool)
    : data.detail ?? meta.description

  return (
    <div
      className={cn(
        "relative h-full w-full overflow-hidden transition-opacity duration-500",
        data.dimmed && "opacity-40"
      )}
    >
      <FlowNodeHandles />

      <div
        className={cn(
          "relative flex h-full min-w-0 flex-col overflow-hidden rounded-xl border bg-background px-3 py-2.5 shadow-sm transition-all duration-500",
          data.highlighted &&
            "ring-2 ring-sky-500/70 ring-offset-1 ring-offset-background",
          isInfra && "rounded-lg bg-muted/30",
          data.status === "active" &&
            (isInfra
              ? "border-emerald-600/50 dark:border-emerald-400/40"
              : "border-foreground shadow-[0_0_0_1px_hsl(var(--foreground)/0.08),0_8px_24px_-10px_hsl(var(--foreground)/0.3)]"),
          data.status === "completed" &&
            (isInfra
              ? "border-emerald-600/25 bg-emerald-50/50 dark:bg-emerald-950/15"
              : "border-foreground/25 bg-muted/40"),
          data.status === "waiting" &&
            "border-amber-500/60 bg-amber-50/80 dark:bg-amber-950/20",
          data.status === "error" && "border-destructive/60 bg-destructive/5",
          data.status === "idle" && "border-border/80"
        )}
      >
        {isActive ? (
          <span
            className={cn(
              "pointer-events-none absolute -inset-px rounded-xl ring-2",
              isInfra ? "ring-emerald-600/10 dark:ring-emerald-400/10" : "ring-foreground/10"
            )}
          />
        ) : null}

        {data.health ? (
          <span
            className={cn(
              "absolute right-2.5 top-2.5 h-2.5 w-2.5 rounded-full",
              healthDotClass(data.health)
            )}
            title={data.health === "healthy" ? "Healthy" : data.health === "down" ? "Down" : "Unknown"}
          />
        ) : null}

        <div className="flex min-h-0 min-w-0 flex-1 items-start gap-2.5">
          <div
            className={cn(
              "flex shrink-0 items-center justify-center rounded-md border",
              isInfra ? "h-8 w-8" : "h-9 w-9",
              isActive
                ? isInfra
                  ? "border-emerald-600/25 bg-emerald-600 text-white dark:border-emerald-400/25 dark:bg-emerald-500"
                  : "border-foreground/20 bg-foreground text-background"
                : "border-border bg-muted/50 text-muted-foreground"
            )}
          >
            <Icon className={cn(isInfra ? "h-4 w-4" : "h-5 w-5")} />
          </div>

          <div className="min-w-0 flex-1 overflow-hidden">
            <div className="flex min-w-0 items-start justify-between gap-1">
              <p
                className={cn(
                  "min-w-0 font-semibold leading-tight tracking-tight",
                  isInfra ? "text-xs" : "text-sm"
                )}
              >
                {meta.label}
              </p>
              <span
                className={cn(
                  "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                  data.status === "active" &&
                    (isInfra
                      ? "bg-emerald-600 text-white dark:bg-emerald-500"
                      : "bg-foreground text-background"),
                  data.status === "completed" && "bg-muted text-foreground",
                  data.status === "waiting" &&
                    "bg-amber-500/15 text-amber-700 dark:text-amber-300",
                  data.status === "error" && "bg-destructive/10 text-destructive",
                  data.status === "idle" && "bg-muted text-muted-foreground"
                )}
              >
                {statusLabel(data.status)}
              </span>
            </div>
            <p className="mt-1 line-clamp-2 overflow-hidden break-words text-[11px] leading-snug text-muted-foreground">
              {detailText}
              {meta.subtitle ? (
                <span className="font-mono text-muted-foreground/70">
                  {" "}
                  · {meta.subtitle}
                </span>
              ) : null}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export const AgentFlowNode = memo(AgentFlowNodeComponent)
