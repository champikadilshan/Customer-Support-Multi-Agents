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

export const CANVAS = {
  width: 1440,
  height: 396,
}

/**
 * Three-tier layout with separated infra columns:
 * - Complaint stack: Ticket API → Ticket DB (vertical)
 * - Sales stack: Sales MCP → Product Graph (vertical)
 */
export const NODE_LAYOUT: Record<AgentNodeId, NodeLayout> = {
  intent_detector: { x: 540, y: 8, w: 220, h: 68 },

  billing: { x: 40, y: 108, w: 220, h: 72 },
  complaint: { x: 540, y: 108, w: 220, h: 72 },
  sales: { x: 1040, y: 108, w: 220, h: 72 },

  billing_db: { x: 40, y: 228, w: 220, h: 64 },

  ticket_api: { x: 360, y: 228, w: 200, h: 64 },
  hitl: { x: 640, y: 228, w: 200, h: 64 },
  ticket_db: { x: 360, y: 314, w: 200, h: 64 },

  sales_mcp: { x: 1040, y: 228, w: 220, h: 64 },
  product_db: { x: 1040, y: 314, w: 220, h: 64 },
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
  {
    id: "collab-b-c",
    from: "billing",
    to: "complaint",
    sourceHandle: "right",
    targetHandle: "left",
    kind: "collaboration",
  },
  {
    id: "collab-c-s",
    from: "complaint",
    to: "sales",
    sourceHandle: "right",
    targetHandle: "left",
    kind: "collaboration",
  },
  {
    id: "collab-s-b",
    from: "sales",
    to: "billing",
    sourceHandle: "source-left",
    targetHandle: "target-right",
    kind: "collaboration",
  },
]

export function mapHandoffToNodeId(agent: string): AgentNodeId | null {
  const normalized = agent.toLowerCase()
  if (normalized.includes("billing")) return "billing"
  if (normalized.includes("complaint")) return "complaint"
  if (normalized.includes("sales")) return "sales"
  if (normalized.includes("intent")) return "intent_detector"
  return null
}
