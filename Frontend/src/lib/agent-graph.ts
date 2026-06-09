export type AgentNodeId =
  | "intent_detector"
  | "billing"
  | "complaint"
  | "sales"
  | "hitl"
  | "billing_db"
  | "sales_mcp"
  | "product_db"
  | "ticket_api"
  | "ticket_db"

export type NodeKind = "orchestrator" | "agent" | "infra"

export type NodeStatus =
  | "idle"
  | "active"
  | "completed"
  | "waiting"
  | "error"

export type EdgeStatus = "idle" | "active" | "completed"

export type GraphNodeState = {
  status: NodeStatus
  detail?: string
  runningTools: string[]
  completedTools: string[]
}

export type GraphEdge = {
  id: string
  from: AgentNodeId
  to: AgentNodeId
  status: EdgeStatus
  kind: "route" | "collaboration" | "data" | "pipeline"
}

export type GraphHandoff = {
  from: string
  to: string
  status: EdgeStatus
  reason?: string
}

export type GraphActivity = {
  id: string
  message: string
  timestamp: number
}

export type AgentGraphState = {
  nodes: Record<AgentNodeId, GraphNodeState>
  edges: GraphEdge[]
  handoffs: GraphHandoff[]
  activities: GraphActivity[]
  routedAgent: AgentNodeId | null
  showComplaintFlow: boolean
  traceConnected: boolean
  lastEventAt: number | null
}

export const NODE_KIND: Record<AgentNodeId, NodeKind> = {
  intent_detector: "orchestrator",
  billing: "agent",
  complaint: "agent",
  sales: "agent",
  hitl: "infra",
  billing_db: "infra",
  sales_mcp: "infra",
  product_db: "infra",
  ticket_api: "infra",
  ticket_db: "infra",
}

export const AGENT_NODES: Record<
  AgentNodeId,
  { label: string; description: string; subtitle?: string }
> = {
  intent_detector: {
    label: "Intent Detector",
    description: "Orchestrator · routes by intent",
    subtitle: ":8001",
  },
  billing: {
    label: "Billing Agent",
    description: "Balance, invoices, payments",
    subtitle: ":8002",
  },
  complaint: {
    label: "Complaint Agent",
    description: "Issues, tickets, disputes",
    subtitle: ":8003",
  },
  sales: {
    label: "Sales Agent",
    description: "Products, plans, promotions",
    subtitle: ":8004",
  },
  hitl: {
    label: "Human Review",
    description: "Approval gate before ticket create",
  },
  billing_db: {
    label: "Billing DB",
    description: "SQLite · accounts & invoices",
  },
  sales_mcp: {
    label: "Sales MCP",
    description: "MCP product tools",
    subtitle: ":8005",
  },
  product_db: {
    label: "Product Graph",
    description: "Neo4j catalog",
  },
  ticket_api: {
    label: "Ticket Service",
    description: "REST API · ticket CRUD",
    subtitle: ":8000",
  },
  ticket_db: {
    label: "Ticket DB",
    description: "SQLite · support tickets",
  },
}

const BASE_EDGES: GraphEdge[] = [
  { id: "route-billing", from: "intent_detector", to: "billing", status: "idle", kind: "route" },
  { id: "route-complaint", from: "intent_detector", to: "complaint", status: "idle", kind: "route" },
  { id: "route-sales", from: "intent_detector", to: "sales", status: "idle", kind: "route" },
  { id: "data-billing-db", from: "billing", to: "billing_db", status: "idle", kind: "data" },
  { id: "data-sales-mcp", from: "sales", to: "sales_mcp", status: "idle", kind: "data" },
  { id: "data-mcp-neo4j", from: "sales_mcp", to: "product_db", status: "idle", kind: "data" },
  { id: "data-complaint-api", from: "complaint", to: "ticket_api", status: "idle", kind: "data" },
  { id: "data-api-db", from: "ticket_api", to: "ticket_db", status: "idle", kind: "data" },
  { id: "pipe-complaint-hitl", from: "complaint", to: "hitl", status: "idle", kind: "pipeline" },
  { id: "pipe-hitl-api", from: "hitl", to: "ticket_api", status: "idle", kind: "pipeline" },
  { id: "collab-b-c", from: "billing", to: "complaint", status: "idle", kind: "collaboration" },
  { id: "collab-c-s", from: "complaint", to: "sales", status: "idle", kind: "collaboration" },
  { id: "collab-s-b", from: "sales", to: "billing", status: "idle", kind: "collaboration" },
]

function createIdleNode(): GraphNodeState {
  return { status: "idle", runningTools: [], completedTools: [] }
}

function createIdleNodes(): AgentGraphState["nodes"] {
  return {
    intent_detector: createIdleNode(),
    billing: createIdleNode(),
    complaint: createIdleNode(),
    sales: createIdleNode(),
    hitl: createIdleNode(),
    billing_db: createIdleNode(),
    sales_mcp: createIdleNode(),
    product_db: createIdleNode(),
    ticket_api: createIdleNode(),
    ticket_db: createIdleNode(),
  }
}

export function createInitialAgentGraphState(): AgentGraphState {
  return {
    nodes: createIdleNodes(),
    edges: BASE_EDGES.map((edge) => ({ ...edge })),
    handoffs: [],
    activities: [],
    routedAgent: null,
    showComplaintFlow: false,
    traceConnected: false,
    lastEventAt: null,
  }
}

function createActivityId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function pushActivity(state: AgentGraphState, message: string): AgentGraphState {
  const activities = [
    { id: createActivityId(), message, timestamp: Date.now() },
    ...state.activities,
  ].slice(0, 12)
  return { ...state, activities }
}

export function setNode(
  state: AgentGraphState,
  nodeId: AgentNodeId,
  status: NodeStatus,
  detail?: string,
  toolState?: Pick<GraphNodeState, "runningTools" | "completedTools">
): AgentGraphState {
  const current = state.nodes[nodeId]
  return {
    ...state,
    nodes: {
      ...state.nodes,
      [nodeId]: {
        status,
        detail,
        runningTools: toolState?.runningTools ?? current.runningTools,
        completedTools: toolState?.completedTools ?? current.completedTools,
      },
    },
  }
}

export function setEdgeById(
  state: AgentGraphState,
  edgeId: string,
  status: EdgeStatus
): AgentGraphState {
  return {
    ...state,
    edges: state.edges.map((edge) =>
      edge.id === edgeId ? { ...edge, status } : edge
    ),
  }
}

export function setEdge(
  state: AgentGraphState,
  from: AgentNodeId,
  to: AgentNodeId,
  status: EdgeStatus
): AgentGraphState {
  return {
    ...state,
    edges: state.edges.map((edge) =>
      edge.from === from && edge.to === to ? { ...edge, status } : edge
    ),
  }
}

export function getEdgeStatus(
  state: AgentGraphState,
  from: AgentNodeId,
  to: AgentNodeId
): EdgeStatus {
  return state.edges.find((edge) => edge.from === from && edge.to === to)?.status ?? "idle"
}

export function mapAgentValue(agent: string | null | undefined): AgentNodeId | null {
  if (!agent) return null
  const normalized = agent.toLowerCase()
  if (normalized.includes("billing")) return "billing"
  if (normalized.includes("complaint")) return "complaint"
  if (normalized.includes("sales")) return "sales"
  if (normalized.includes("intent")) return "intent_detector"
  return null
}

export const AGENT_NODE_IDS: AgentNodeId[] = [
  "intent_detector",
  "billing",
  "complaint",
  "sales",
  "hitl",
  "billing_db",
  "sales_mcp",
  "product_db",
  "ticket_api",
  "ticket_db",
]
