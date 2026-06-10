import type { AgentNodeId } from "@/lib/agent-graph"

export type NodeLayout = {
  x: number
  y: number
  w: number
  h: number
}

export type StaticEdge = {
  id: string
  from: AgentNodeId
  to: AgentNodeId
  sourceHandle: string
  targetHandle: string
  kind: "route" | "pipeline" | "collaboration" | "data"
}

/**
 * Four-column layout with explicit gaps so infra nodes never overlap.
 * Columns: Billing | Complaint+Ticket | HITL | Sales+MCP
 */
export const CANVAS = {
  width: 1040,
  height: 492,
}

const COL = {
  billing: 0,
  complaint: 270,
  hitl: 540,
  sales: 810,
} as const

const NODE_W = 210
const NODE_H_AGENT = 86
const NODE_H_INFRA = 78

/** Shared vertical gap between graph tiers (orchestrator → agents → infra). */
const ROW_GAP = 56
const ORCHESTRATOR_H = 82
const AGENT_ROW_Y = ORCHESTRATOR_H + ROW_GAP
const INFRA_ROW_Y = AGENT_ROW_Y + NODE_H_AGENT + ROW_GAP
const DEEP_INFRA_ROW_Y = INFRA_ROW_Y + NODE_H_INFRA + ROW_GAP

export const NODE_LAYOUT: Record<AgentNodeId, NodeLayout> = {
  intent_detector: {
    x: (CANVAS.width - 230) / 2,
    y: 0,
    w: 230,
    h: ORCHESTRATOR_H,
  },

  billing: { x: COL.billing, y: AGENT_ROW_Y, w: NODE_W, h: NODE_H_AGENT },
  complaint: { x: COL.complaint, y: AGENT_ROW_Y, w: NODE_W, h: NODE_H_AGENT },
  sales: { x: COL.sales, y: AGENT_ROW_Y, w: NODE_W, h: NODE_H_AGENT },

  billing_db: { x: COL.billing, y: INFRA_ROW_Y, w: NODE_W, h: NODE_H_INFRA },

  ticket_api: { x: COL.complaint, y: INFRA_ROW_Y, w: NODE_W, h: NODE_H_INFRA },
  hitl: { x: COL.hitl, y: INFRA_ROW_Y, w: NODE_W, h: NODE_H_INFRA },
  ticket_db: { x: COL.complaint, y: DEEP_INFRA_ROW_Y, w: NODE_W, h: NODE_H_INFRA },

  sales_mcp: { x: COL.sales, y: INFRA_ROW_Y, w: NODE_W, h: NODE_H_INFRA },
  product_db: { x: COL.sales, y: DEEP_INFRA_ROW_Y, w: NODE_W, h: NODE_H_INFRA },
}

export const STATIC_EDGES: StaticEdge[] = [
  {
    id: "route-billing",
    from: "intent_detector",
    to: "billing",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "route",
  },
  {
    id: "route-complaint",
    from: "intent_detector",
    to: "complaint",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "route",
  },
  {
    id: "route-sales",
    from: "intent_detector",
    to: "sales",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "route",
  },
  {
    id: "data-billing-db",
    from: "billing",
    to: "billing_db",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "data",
  },
  {
    id: "data-sales-mcp",
    from: "sales",
    to: "sales_mcp",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "data",
  },
  {
    id: "data-mcp-neo4j",
    from: "sales_mcp",
    to: "product_db",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "data",
  },
  {
    id: "data-complaint-api",
    from: "complaint",
    to: "ticket_api",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "data",
  },
  {
    id: "data-api-db",
    from: "ticket_api",
    to: "ticket_db",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "data",
  },
  {
    id: "pipe-complaint-hitl",
    from: "complaint",
    to: "hitl",
    sourceHandle: "bottom",
    targetHandle: "top",
    kind: "pipeline",
  },
  {
    id: "pipe-hitl-api",
    from: "hitl",
    to: "ticket_api",
    sourceHandle: "source-left",
    targetHandle: "target-right",
    kind: "pipeline",
  },
]

export function mapHandoffToNodeId(agent: string): AgentNodeId | null {
  const normalized = agent.toLowerCase()
  if (normalized === "orchestrator" || normalized.includes("intent")) {
    return "intent_detector"
  }
  if (normalized.includes("billing")) return "billing"
  if (normalized.includes("complaint")) return "complaint"
  if (normalized.includes("sales")) return "sales"
  return null
}
