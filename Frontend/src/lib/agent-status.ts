import type { AgentGraphState, AgentNodeId, GraphActivity } from "@/lib/agent-graph"

const TOOL_PROGRESS_MESSAGES: Record<string, string> = {
  dispatch_billing_agent: "Collecting billing info",
  dispatch_complaint_agent: "Collecting complaint info",
  dispatch_sales_agent: "Collecting sales info",
  get_account_balance: "Checking balance",
  get_invoice_history: "Fetching invoices",
  get_payment_methods: "Fetching payments",
  get_complaint_history: "Fetching complaints",
  get_ticket_status: "Checking ticket",
  categorize_complaint: "Categorizing issue",
  stage_ticket_creation: "Staging ticket",
  create_ticket: "Creating ticket",
  get_product_catalog: "Browsing plans",
  get_active_promotions: "Checking deals",
  check_product_availability: "Checking availability",
  call_billing_agent: "Consulting billing",
  call_complaint_agent: "Consulting complaints",
  call_sales_agent: "Consulting sales",
}

const AGENT_PROGRESS_MESSAGES: Record<AgentNodeId, string> = {
  intent_detector: "Routing request",
  billing: "Checking billing",
  complaint: "Handling complaint",
  sales: "Finding options",
  hitl: "Awaiting confirmation",
  billing_db: "Loading account",
  sales_mcp: "Searching catalog",
  product_db: "Searching plans",
  ticket_api: "Checking records",
  ticket_db: "Saving ticket",
}

const SPECIALIST_AGENTS: AgentNodeId[] = [
  "billing",
  "complaint",
  "sales",
  "intent_detector",
]

export function formatAgentName(agent: string | null | undefined) {
  if (!agent) return "support"

  const normalized = agent.toLowerCase()

  if (normalized.includes("billing")) return "billing"
  if (normalized.includes("sales")) return "sales"
  if (normalized.includes("complaint")) return "complaint"
  if (normalized.includes("intent") || normalized.includes("orchestrator")) {
    return "routing"
  }

  return agent.replace(/_/g, " ")
}

export function getToolProgressMessage(toolId: string | null | undefined) {
  if (!toolId) return "Processing"

  return (
    TOOL_PROGRESS_MESSAGES[toolId] ??
    toolId
      .replace(/^dispatch_/, "")
      .replace(/_/g, " ")
      .replace(/\b\w/g, (char) => char.toUpperCase())
  )
}

function mapHandoffAgent(agent: string): AgentNodeId | null {
  const normalized = agent.toLowerCase()

  if (normalized.includes("billing")) return "billing"
  if (normalized.includes("complaint")) return "complaint"
  if (normalized.includes("sales")) return "sales"
  if (normalized.includes("orchestrator") || normalized.includes("intent")) {
    return "intent_detector"
  }

  return null
}

function formatHumanActivityMessage(activity: GraphActivity) {
  if (activity.tool) {
    return getToolProgressMessage(activity.tool)
  }

  switch (activity.eventType) {
    case "orchestrator_dispatch":
      return AGENT_PROGRESS_MESSAGES.intent_detector
    case "agent_start": {
      const agentId = mapHandoffAgent(activity.agent ?? "")
      if (agentId) return AGENT_PROGRESS_MESSAGES[agentId]
      return "Routing request"
    }
    case "agent_handoff": {
      const toId = mapHandoffAgent(activity.agent ?? "")
      if (toId) return AGENT_PROGRESS_MESSAGES[toId]
      return "Handing off"
    }
    case "hitl_requested":
      return "Ready for review"
    case "hitl_resumed":
      return "Resuming"
    case "tool_end":
      return "Finalizing reply"
    default:
      return "Processing"
  }
}

function findRunningTool(graph: AgentGraphState) {
  for (const agentId of SPECIALIST_AGENTS) {
    const runningTools = graph.nodes[agentId].runningTools
    if (runningTools.length > 0) {
      return runningTools[runningTools.length - 1]
    }
  }

  return null
}

function findActiveInfraMessage(graph: AgentGraphState) {
  const infraNodes: AgentNodeId[] = [
    "ticket_db",
    "ticket_api",
    "billing_db",
    "product_db",
    "sales_mcp",
  ]

  for (const nodeId of infraNodes) {
    if (graph.nodes[nodeId].status === "active") {
      return AGENT_PROGRESS_MESSAGES[nodeId]
    }
  }

  return null
}

export function getChatProgressMessage(
  graph: AgentGraphState | null | undefined,
  options?: {
    activeToolName?: string | null
  }
) {
  if (options?.activeToolName) {
    return getToolProgressMessage(options.activeToolName)
  }

  if (!graph) {
    return "Reading message"
  }

  if (
    graph.nodes.hitl.status === "waiting" ||
    graph.nodes.complaint.status === "waiting"
  ) {
    return AGENT_PROGRESS_MESSAGES.hitl
  }

  const runningTool = findRunningTool(graph)
  if (runningTool) {
    return getToolProgressMessage(runningTool)
  }

  const activeHandoff = graph.handoffs.find(
    (handoff) => handoff.status === "active"
  )
  if (activeHandoff) {
    const toAgent = mapHandoffAgent(activeHandoff.to)
    if (toAgent) return AGENT_PROGRESS_MESSAGES[toAgent]
    return "Handing off"
  }

  if (graph.routedAgent) {
    const routed = graph.nodes[graph.routedAgent]
    if (routed.status === "active" || routed.status === "waiting") {
      return AGENT_PROGRESS_MESSAGES[graph.routedAgent]
    }
  }

  for (const agentId of ["billing", "complaint", "sales"] as AgentNodeId[]) {
    if (graph.nodes[agentId].status === "active") {
      return AGENT_PROGRESS_MESSAGES[agentId]
    }
  }

  if (graph.nodes.intent_detector.status === "active") {
    return AGENT_PROGRESS_MESSAGES.intent_detector
  }

  const infraMessage = findActiveInfraMessage(graph)
  if (infraMessage) {
    return infraMessage
  }

  const latestActivity = graph.activities.at(-1)
  if (latestActivity && graph.traceConnected) {
    return formatHumanActivityMessage(latestActivity)
  }

  return "Reading message"
}

/** @deprecated Use getChatProgressMessage for live trace-driven status text. */
export function getAgentStatusMessage({
  activeAgent,
  activeIntent,
  hasActiveToolCall,
}: {
  activeAgent: string | null
  activeIntent: string | null
  hasActiveToolCall: boolean
}) {
  if (hasActiveToolCall) {
    return "Processing"
  }

  if (activeAgent) {
    const agentId = mapHandoffAgent(activeAgent)
    if (agentId) return AGENT_PROGRESS_MESSAGES[agentId]
    return `Checking ${formatAgentName(activeAgent)}`
  }

  if (activeIntent) {
    return `Checking ${activeIntent}`
  }

  return "Reading message"
}
