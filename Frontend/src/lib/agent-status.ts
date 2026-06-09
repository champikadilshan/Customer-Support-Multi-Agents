export function formatAgentName(agent: string | null | undefined) {
  if (!agent) return "support"

  const normalized = agent.toLowerCase()

  if (normalized.includes("billing")) return "billing"
  if (normalized.includes("sales")) return "sales"
  if (normalized.includes("complaint")) return "complaint"
  if (normalized.includes("intent")) return "routing"

  return agent.replace(/_/g, " ")
}

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
    return "Running tools in the background"
  }

  if (activeAgent) {
    return `Connecting to ${formatAgentName(activeAgent)} specialist`
  }

  if (activeIntent) {
    return `Routing your ${activeIntent} request`
  }

  return "Analyzing your request"
}
