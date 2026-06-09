export type AgentNodeId =
  | "intent_detector"
  | "billing"
  | "complaint"
  | "sales"
  | "tools"
  | "hitl"
  | "ticket_service"

export type NodeStatus =
  | "idle"
  | "active"
  | "completed"
  | "waiting"
  | "error"

export type EdgeStatus = "idle" | "active" | "completed"

export type GraphEdge = {
  from: AgentNodeId
  to: AgentNodeId
  status: EdgeStatus
}

export type GraphActivity = {
  id: string
  message: string
  timestamp: number
}

export type AgentGraphState = {
  nodes: Record<AgentNodeId, { status: NodeStatus; detail?: string }>
  edges: GraphEdge[]
  activities: GraphActivity[]
  routedAgent: AgentNodeId | null
  showComplaintFlow: boolean
}

export const AGENT_NODES: Record<
  AgentNodeId,
  { label: string; description: string }
> = {
  intent_detector: {
    label: "Intent Detector",
    description: "Routes your message to the right specialist",
  },
  billing: {
    label: "Billing Agent",
    description: "Account balance, invoices, payments",
  },
  complaint: {
    label: "Complaint Agent",
    description: "Issues, disputes, ticket staging",
  },
  sales: {
    label: "Sales Agent",
    description: "Products, plans, promotions",
  },
  tools: {
    label: "Tools",
    description: "Backend tool calls",
  },
  hitl: {
    label: "Human Review",
    description: "Approval before ticket creation",
  },
  ticket_service: {
    label: "Ticket Service",
    description: "Persists support tickets",
  },
}

const BASE_EDGES: GraphEdge[] = [
  { from: "intent_detector", to: "billing", status: "idle" },
  { from: "intent_detector", to: "complaint", status: "idle" },
  { from: "intent_detector", to: "sales", status: "idle" },
  { from: "complaint", to: "tools", status: "idle" },
  { from: "tools", to: "hitl", status: "idle" },
  { from: "hitl", to: "ticket_service", status: "idle" },
]

function createIdleNodes(): AgentGraphState["nodes"] {
  return {
    intent_detector: { status: "idle" },
    billing: { status: "idle" },
    complaint: { status: "idle" },
    sales: { status: "idle" },
    tools: { status: "idle" },
    hitl: { status: "idle" },
    ticket_service: { status: "idle" },
  }
}

export function createInitialAgentGraphState(): AgentGraphState {
  return {
    nodes: createIdleNodes(),
    edges: BASE_EDGES.map((edge) => ({ ...edge })),
    activities: [],
    routedAgent: null,
    showComplaintFlow: false,
  }
}

function createActivityId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function pushActivity(
  state: AgentGraphState,
  message: string
): AgentGraphState {
  const activities = [
    { id: createActivityId(), message, timestamp: Date.now() },
    ...state.activities,
  ].slice(0, 8)

  return { ...state, activities }
}

function setNode(
  state: AgentGraphState,
  nodeId: AgentNodeId,
  status: NodeStatus,
  detail?: string
): AgentGraphState {
  return {
    ...state,
    nodes: {
      ...state.nodes,
      [nodeId]: { status, detail },
    },
  }
}

function setEdge(
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

export function mapAgentValue(agent: string | null | undefined): AgentNodeId | null {
  if (!agent) return null

  const normalized = agent.toLowerCase()
  if (normalized.includes("billing")) return "billing"
  if (normalized.includes("complaint")) return "complaint"
  if (normalized.includes("sales")) return "sales"
  if (normalized.includes("intent")) return "intent_detector"
  return null
}

export function reduceAgentGraphOnStreamStart(
  state: AgentGraphState
): AgentGraphState {
  const next = createInitialAgentGraphState()
  return pushActivity(
    setNode(
      setEdge(next, "intent_detector", "billing", "idle"),
      "intent_detector",
      "active",
      "Detecting intent..."
    ),
    "Message received — analyzing intent"
  )
}

export function reduceAgentGraphOnIntent(
  state: AgentGraphState,
  intent: string,
  agent: string
): AgentGraphState {
  const routed = mapAgentValue(agent)
  let next = pushActivity(
    setNode(state, "intent_detector", "completed", `Intent: ${intent}`),
    `Intent detected: ${intent}`
  )

  if (!routed) return next

  next = {
    ...next,
    routedAgent: routed,
    showComplaintFlow: routed === "complaint",
  }

  next = setNode(next, routed, "active", "Handling request...")
  next = setEdge(next, "intent_detector", routed, "active")

  return pushActivity(next, `Routing to ${AGENT_NODES[routed].label}`)
}

export function reduceAgentGraphOnToolCall(
  state: AgentGraphState,
  toolName: string
): AgentGraphState {
  if (state.routedAgent !== "complaint") {
    const agent = state.routedAgent
    if (!agent) return state

    return pushActivity(
      setNode(state, agent, "active", `Running ${toolName}`),
      `${AGENT_NODES[agent].label} calling ${toolName}`
    )
  }

  let next = setNode(state, "complaint", "active", "Running tools...")
  next = setNode(next, "tools", "active", toolName)
  next = setEdge(next, "complaint", "tools", "active")

  return pushActivity(next, `Complaint agent calling ${toolName}`)
}

export function reduceAgentGraphOnHitlRequest(
  state: AgentGraphState
): AgentGraphState {
  let next = setNode(state, "tools", "completed", "Ticket staged")
  next = setNode(next, "hitl", "waiting", "Awaiting approval")
  next = setEdge(next, "tools", "hitl", "active")

  return pushActivity(next, "Waiting for human approval")
}

export function reduceAgentGraphOnHitlResponse(
  state: AgentGraphState,
  response: "yes" | "no"
): AgentGraphState {
  let next = setNode(state, "hitl", "completed", response === "yes" ? "Approved" : "Declined")
  next = setEdge(next, "tools", "hitl", "completed")

  if (response === "yes") {
    next = setNode(next, "ticket_service", "active", "Creating ticket...")
    next = setEdge(next, "hitl", "ticket_service", "active")
    return pushActivity(next, "Human approved — creating ticket")
  }

  next = setNode(next, "complaint", "active", "Finalizing response...")
  return pushActivity(next, "Human declined — skipping ticket creation")
}

export function reduceAgentGraphOnToken(
  state: AgentGraphState
): AgentGraphState {
  const agent = state.routedAgent
  if (!agent) return state

  if (state.nodes.ticket_service.status === "active") {
    return setNode(state, "ticket_service", "active", "Writing ticket record...")
  }

  if (state.nodes[agent].status === "waiting") return state

  return setNode(state, agent, "active", "Generating response...")
}

export function reduceAgentGraphOnDone(
  state: AgentGraphState
): AgentGraphState {
  let next = state

  if (next.nodes.ticket_service.status === "active") {
    next = setNode(next, "ticket_service", "completed", "Ticket saved")
    next = setEdge(next, "hitl", "ticket_service", "completed")
  }

  if (next.routedAgent) {
    next = setNode(next, next.routedAgent, "completed", "Done")
    next = setEdge(next, "intent_detector", next.routedAgent, "completed")

    if (next.routedAgent === "complaint") {
      if (next.nodes.tools.status !== "idle") {
        next = setNode(next, "tools", "completed")
        next = setEdge(next, "complaint", "tools", "completed")
      }
      if (next.nodes.hitl.status === "waiting") {
        next = setNode(next, "hitl", "completed")
      }
    }
  }

  return pushActivity(next, "Request completed")
}

export function reduceAgentGraphOnError(
  state: AgentGraphState,
  message: string
): AgentGraphState {
  const activeNode =
    (Object.entries(state.nodes).find(
      ([, node]) => node.status === "active" || node.status === "waiting"
    )?.[0] as AgentNodeId | undefined) ??
    state.routedAgent ??
    "intent_detector"

  return pushActivity(
    setNode(state, activeNode, "error", "Failed"),
    message
  )
}

export function getEdgeStatus(
  state: AgentGraphState,
  from: AgentNodeId,
  to: AgentNodeId
): EdgeStatus {
  return (
    state.edges.find((edge) => edge.from === from && edge.to === to)?.status ??
    "idle"
  )
}
