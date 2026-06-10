import {
  createInitialAgentGraphState,
  mapAgentValue,
  pushActivity,
  setEdge,
  setNode,
  type AgentGraphState,
  type AgentNodeId,
  type EdgeStatus,
  type GraphActivity,
} from "@/lib/agent-graph"
import {
  formatToolLabel,
  INTER_AGENT_TOOL_TARGETS,
  isInterAgentTool,
  TOOL_INFRA_ACTIVATION,
} from "@/lib/agent-tools"

export type TraceEventType =
  | "orchestrator_dispatch"
  | "agent_start"
  | "agent_end"
  | "agent_handoff"
  | "tool_start"
  | "tool_end"
  | "hitl_requested"
  | "hitl_resumed"
  | "error"

export type TraceEvent = {
  type: TraceEventType
  session_id: string
  ts: string
  agent?: string
  tool?: string
  user_message?: string
  request_id?: string
  from_agent?: string
  to_agent?: string
  reason?: string
  message?: string
  response?: string
  status?: string
  is_internal?: boolean
  triggered_by?: string
  ticket_preview?: Record<string, unknown>
  duration_ms?: number
}

export function mapTraceAgent(agent: string | undefined): AgentNodeId | null {
  if (!agent) return null
  if (agent === "orchestrator" || agent === "intent_detector") {
    return "intent_detector"
  }
  return mapAgentValue(agent)
}

/** Nodes that should flash success then return to idle after a transient event. */
export function getFlashResetTargets(event: TraceEvent): AgentNodeId[] {
  const targets = new Set<AgentNodeId>()

  if (event.type === "agent_end" && event.status === "success") {
    const agentId = mapTraceAgent(event.agent)
    if (agentId) targets.add(agentId)
  }

  if (event.type === "tool_end" && event.tool) {
    const config = TOOL_INFRA_ACTIVATION[event.tool]
    if (config) {
      for (const nodeId of config.nodes) {
        targets.add(nodeId)
      }
    }
  }

  return Array.from(targets)
}

function resetTurnState(state: AgentGraphState): AgentGraphState {
  const next = createInitialAgentGraphState()

  return {
    ...next,
    activities: state.activities,
    traceConnected: state.traceConnected,
    lastEventAt: state.lastEventAt,
  }
}

function upsertHandoff(
  state: AgentGraphState,
  from: string,
  to: string,
  status: EdgeStatus,
  reason?: string
): AgentGraphState {
  const existing = state.handoffs.find(
    (handoff) => handoff.from === from && handoff.to === to
  )

  if (existing) {
    return {
      ...state,
      handoffs: state.handoffs.map((handoff) =>
        handoff.from === from && handoff.to === to
          ? { ...handoff, status, reason: reason ?? handoff.reason }
          : handoff
      ),
    }
  }

  return {
    ...state,
    handoffs: [...state.handoffs, { from, to, status, reason }],
  }
}

function markToolRunning(
  state: AgentGraphState,
  agentId: AgentNodeId,
  tool: string
): AgentGraphState {
  const node = state.nodes[agentId]
  const runningTools = node.runningTools.includes(tool)
    ? node.runningTools
    : [...node.runningTools, tool]

  return setNode(state, agentId, "active", `Running ${formatToolLabel(tool)}`, {
    runningTools,
    completedTools: node.completedTools.filter((item) => item !== tool),
  })
}

function markToolCompleted(
  state: AgentGraphState,
  agentId: AgentNodeId,
  tool: string
): AgentGraphState {
  const node = state.nodes[agentId]
  const runningTools = node.runningTools.filter((item) => item !== tool)
  const completedTools = node.completedTools.includes(tool)
    ? node.completedTools
    : [...node.completedTools, tool]

  return setNode(state, agentId, node.status === "idle" ? "active" : node.status, node.detail, {
    runningTools,
    completedTools,
  })
}

function activateToolInfra(state: AgentGraphState, tool: string): AgentGraphState {
  const config = TOOL_INFRA_ACTIVATION[tool]
  if (!config) return state

  let next = state
  for (const nodeId of config.nodes) {
    next = setNode(next, nodeId, "active", formatToolLabel(tool))
  }
  for (const [from, to] of config.edges) {
    next = setEdge(next, from, to, "active")
  }

  return next
}

function completeToolInfra(state: AgentGraphState, tool: string): AgentGraphState {
  const config = TOOL_INFRA_ACTIVATION[tool]
  if (!config) return state

  let next = state
  for (const nodeId of config.nodes) {
    const node = next.nodes[nodeId]
    next = setNode(
      next,
      nodeId,
      node.status === "waiting" ? "waiting" : "completed",
      node.detail
    )
  }
  for (const [from, to] of config.edges) {
    next = setEdge(next, from, to, "completed")
  }

  return next
}

function activatePrimaryRoute(
  state: AgentGraphState,
  agentId: AgentNodeId,
  detail: string
): AgentGraphState {
  let next = setNode(state, "intent_detector", "active", "Dispatching...")
  next = setNode(next, agentId, "active", detail)
  next = setEdge(next, "intent_detector", agentId, "active")
  next = {
    ...next,
    routedAgent: agentId,
  }

  for (const specialist of ["billing", "complaint", "sales"] as AgentNodeId[]) {
    if (specialist !== agentId) {
      next = setEdge(next, "intent_detector", specialist, "idle")
    }
  }

  return next
}

function resolveHighlightNode(event: TraceEvent): AgentNodeId | undefined {
  const agentId = mapTraceAgent(event.agent)
  if (agentId) return agentId

  if (event.type === "orchestrator_dispatch") return "intent_detector"

  if (event.type === "agent_handoff") {
    return mapTraceAgent(event.to_agent) ?? undefined
  }

  if (event.tool) {
    const config = TOOL_INFRA_ACTIVATION[event.tool]
    if (config?.nodes[0]) return config.nodes[0]
  }

  return undefined
}

function formatActivityMessage(event: TraceEvent): string {
  switch (event.type) {
    case "orchestrator_dispatch":
      return event.user_message
        ? `Orchestrator dispatch: ${event.user_message}`
        : "Orchestrator dispatch"
    case "agent_start":
      return event.is_internal
        ? `${event.agent} started (internal from ${event.triggered_by})`
        : `${event.agent} agent started`
    case "agent_end":
      return `${event.agent} agent finished (${event.status ?? "success"})`
    case "agent_handoff":
      return `${event.from_agent} → ${event.to_agent}: ${event.reason ?? "handoff"}`
    case "tool_start":
      return `${event.agent} running ${formatToolLabel(event.tool ?? "tool")}`
    case "tool_end":
      return `${event.agent} completed ${formatToolLabel(event.tool ?? "tool")}`
    case "hitl_requested":
      return "Human approval requested before ticket creation"
    case "hitl_resumed":
      return `Human responded: ${event.response}`
    case "error":
      return event.message ?? "An error occurred"
    default:
      return "Trace event received"
  }
}

function buildActivity(event: TraceEvent): Omit<GraphActivity, "id"> {
  return {
    message: formatActivityMessage(event),
    timestamp: Date.parse(event.ts) || Date.now(),
    eventType: event.type,
    agent: event.agent ?? event.from_agent,
    tool: event.tool,
    durationMs: event.duration_ms,
    highlightNodeId: resolveHighlightNode(event),
  }
}

export function reduceAgentGraphOnTraceEvent(
  state: AgentGraphState,
  event: TraceEvent
): AgentGraphState {
  let next: AgentGraphState = {
    ...state,
    traceConnected: true,
    lastEventAt: Date.parse(event.ts) || Date.now(),
  }

  switch (event.type) {
    case "orchestrator_dispatch": {
      next = resetTurnState(next)
      const preview = event.user_message?.slice(0, 80) ?? "Processing request..."
      next = setNode(next, "intent_detector", "active", preview)
      break
    }

    case "agent_start": {
      const agentId = mapTraceAgent(event.agent)
      if (!agentId || agentId === "intent_detector") break

      if (!event.is_internal) {
        if (next.routedAgent !== agentId) {
          next = activatePrimaryRoute(next, agentId, "Handling request...")
        } else {
          next = setNode(next, agentId, "active", "Handling request...")
          next = setEdge(next, "intent_detector", agentId, "active")
        }
      } else {
        const parentId = mapTraceAgent(event.triggered_by)
        if (parentId && parentId !== agentId) {
          next = setNode(
            next,
            parentId,
            "active",
            `Waiting on ${event.agent ?? "agent"}...`
          )
          next = setEdge(next, parentId, agentId, "active")
        }
        next = setNode(
          next,
          agentId,
          "active",
          `Internal call from ${event.triggered_by ?? "agent"}`
        )
        next = upsertHandoff(
          next,
          event.triggered_by ?? "unknown",
          event.agent ?? "unknown",
          "active",
          "Internal agent call"
        )
      }
      break
    }

    case "agent_end": {
      const agentId = mapTraceAgent(event.agent)
      if (!agentId) break

      if (event.status === "hitl_suspended") {
        next = setNode(next, agentId, "waiting", "Awaiting human input", {
          runningTools: [],
          completedTools: next.nodes[agentId].completedTools,
        })
        if (agentId === "complaint") {
          next = setNode(next, "hitl", "waiting", "Awaiting human input")
          next = setEdge(next, "complaint", "hitl", "active")
        }
      } else if (event.status === "success") {
        next = setNode(next, agentId, "completed", "Done", {
          runningTools: [],
          completedTools: next.nodes[agentId].completedTools,
        })
      } else {
        next = setNode(next, agentId, "error", event.message ?? "Failed", {
          runningTools: [],
          completedTools: next.nodes[agentId].completedTools,
        })
      }

      if (event.is_internal && event.triggered_by) {
        next = upsertHandoff(
          next,
          event.triggered_by,
          event.agent ?? "unknown",
          "completed"
        )
        const parentId = mapTraceAgent(event.triggered_by)
        if (parentId) {
          next = setEdge(next, parentId, agentId, "completed")
        }
      }

      if (next.routedAgent === agentId && !event.is_internal) {
        next = setEdge(next, "intent_detector", agentId, "completed")
      }
      break
    }

    case "agent_handoff": {
      const fromId = mapTraceAgent(event.from_agent)
      const toId = mapTraceAgent(event.to_agent)

      next = upsertHandoff(
        next,
        event.from_agent ?? "unknown",
        event.to_agent ?? "unknown",
        "active",
        event.reason
      )

      if (fromId && toId) {
        next = setEdge(next, fromId, toId, "active")
        if (toId !== "intent_detector") {
          next = setNode(next, toId, "active", event.reason ?? "Handoff in progress...")
          next = { ...next, routedAgent: toId }
        }
        if (fromId) {
          next = setNode(next, fromId, "active", `Handoff to ${event.to_agent}...`)
        }
      }
      break
    }

    case "tool_start": {
      const agentId = mapTraceAgent(event.agent)
      if (!agentId || !event.tool) break

      next = markToolRunning(next, agentId, event.tool)

      if (isInterAgentTool(event.tool)) {
        const target = INTER_AGENT_TOOL_TARGETS[event.tool]
        if (target) {
          next = setEdge(next, agentId, target, "active")
        }
      } else {
        next = activateToolInfra(next, event.tool)
      }
      break
    }

    case "tool_end": {
      const agentId = mapTraceAgent(event.agent)
      if (!agentId || !event.tool) break

      next = markToolCompleted(next, agentId, event.tool)

      if (isInterAgentTool(event.tool)) {
        const target = INTER_AGENT_TOOL_TARGETS[event.tool]
        if (target) {
          next = setEdge(next, agentId, target, "completed")
        }
      } else {
        next = completeToolInfra(next, event.tool)
      }
      break
    }

    case "hitl_requested":
      next = setNode(next, "complaint", "waiting", "Awaiting approval")
      next = setNode(next, "hitl", "waiting", "Awaiting approval")
      next = setEdge(next, "complaint", "hitl", "active")
      break

    case "hitl_resumed": {
      const approved =
        event.response?.toLowerCase().includes("yes") ||
        event.response?.toLowerCase().includes("approve")

      next = setNode(next, "complaint", "active", "Resuming after approval")
      next = setNode(next, "hitl", "completed", approved ? "Approved" : "Declined")
      next = setEdge(next, "complaint", "hitl", "completed")

      if (approved) {
        next = setNode(next, "ticket_api", "active", "Creating ticket...")
        next = setNode(next, "ticket_db", "active", "Persisting ticket...")
        next = setEdge(next, "complaint", "ticket_api", "active")
        next = setEdge(next, "ticket_api", "ticket_db", "active")
      }
      break
    }

    case "error": {
      const agentId = mapTraceAgent(event.agent) ?? next.routedAgent ?? "intent_detector"
      next = setNode(next, agentId, "error", event.message ?? "Failed")
      break
    }
  }

  return pushActivity(next, buildActivity(event))
}

export async function* parseTraceStream(
  body: ReadableStream<Uint8Array> | null
): AsyncGenerator<TraceEvent> {
  if (!body) return

  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split("\n\n")
    buffer = frames.pop() ?? ""

    for (const frame of frames) {
      const event = parseTraceFrame(frame)
      if (event) yield event
    }
  }

  if (buffer.trim()) {
    const event = parseTraceFrame(buffer)
    if (event) yield event
  }
}

function parseTraceFrame(frame: string): TraceEvent | null {
  const dataLine = frame
    .split("\n")
    .find((line) => line.startsWith("data:"))

  if (!dataLine) return null

  try {
    return JSON.parse(dataLine.slice(5).trim()) as TraceEvent
  } catch {
    return null
  }
}

export async function consumeTraceStream(
  sessionId: string,
  onEvent: (event: TraceEvent) => void,
  signal?: AbortSignal
) {
  const url = `/api/chat/trace/${encodeURIComponent(sessionId)}`

  const response = await fetch(url, {
    method: "GET",
    signal,
    cache: "no-store",
    headers: {
      Accept: "text/event-stream",
    },
  })

  if (!response.ok) {
    const error = new Error(`Trace stream failed with status ${response.status}`)
    ;(error as Error & { status?: number }).status = response.status
    throw error
  }

  for await (const event of parseTraceStream(response.body)) {
    if (signal?.aborted) break
    onEvent(event)
  }
}

const TRACE_RETRY_MS = 400
const TRACE_MAX_RETRIES = 30

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"))
      return
    }

    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort)
      resolve()
    }, ms)

    const onAbort = () => {
      window.clearTimeout(timer)
      reject(new DOMException("Aborted", "AbortError"))
    }

    signal?.addEventListener("abort", onAbort, { once: true })
  })
}

/** Subscribe to GET /chat/trace/{sessionId} and apply events until aborted. */
export async function connectAgentTrace(
  sessionId: string,
  onEvent: (event: TraceEvent) => void,
  signal?: AbortSignal
) {
  let retries = 0

  while (!signal?.aborted) {
    try {
      await consumeTraceStream(sessionId, onEvent, signal)
      return
    } catch (error) {
      if ((error as Error).name === "AbortError") return

      const status = (error as Error & { status?: number }).status
      if (status === 404 && retries < TRACE_MAX_RETRIES) {
        retries += 1
        await sleep(TRACE_RETRY_MS, signal)
        continue
      }

      throw error
    }
  }
}

export async function fetchTraceReplay(sessionId: string): Promise<TraceEvent[]> {
  const response = await fetch(
    `/api/chat/trace/${encodeURIComponent(sessionId)}/replay`,
    { cache: "no-store" }
  )

  if (!response.ok) {
    throw new Error(`Trace replay failed with status ${response.status}`)
  }

  const payload = (await response.json()) as { events?: TraceEvent[] }
  return payload.events ?? []
}
