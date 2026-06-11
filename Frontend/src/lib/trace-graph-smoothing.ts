import {
  AGENT_NODE_IDS,
  type AgentGraphState,
  type AgentNodeId,
  type EdgeStatus,
  type GraphEdge,
  type GraphNodeState,
  type NodeStatus,
} from "@/lib/agent-graph"

/** Every node stays visibly RUNNING for at least this long before dimming. */
export const MIN_ACTIVE_VISIBLE_MS = 5000

/** Extra hold for Ticket Service — create_ticket trace events can fire back-to-back. */
export const TICKET_SERVICE_ACTIVE_MS = 5000

/** Brief DONE state before returning to idle (after the active hold). */
export const MIN_COMPLETED_VISIBLE_MS = 800

/** Edges stay highlighted at least as long as the nodes they connect. */
export const MIN_EDGE_VISIBLE_MS = 5000

function getNodeActiveHoldMs(nodeId: AgentNodeId): number {
  if (nodeId === "ticket_api") return TICKET_SERVICE_ACTIVE_MS
  return MIN_ACTIVE_VISIBLE_MS
}

function nodeRank(status: NodeStatus): number {
  switch (status) {
    case "waiting":
      return 4
    case "active":
      return 3
    case "error":
      return 2
    case "completed":
      return 1
    default:
      return 0
  }
}

function edgeRank(status: EdgeStatus): number {
  switch (status) {
    case "active":
      return 2
    case "completed":
      return 1
    default:
      return 0
  }
}

function toCompleted(node: GraphNodeState): GraphNodeState {
  return {
    ...node,
    status: "completed",
    detail: "Done",
    runningTools: [],
  }
}

export type GraphSmoothingClock = {
  nodeActiveSince: Map<AgentNodeId, number>
  nodeCompletedSince: Map<AgentNodeId, number>
  edgeLitSince: Map<string, number>
}

export function createGraphSmoothingClock(): GraphSmoothingClock {
  return {
    nodeActiveSince: new Map(),
    nodeCompletedSince: new Map(),
    edgeLitSince: new Map(),
  }
}

export type SmoothingResync = {
  delayMs: number
}

export function smoothGraphDisplay(
  display: AgentGraphState,
  logical: AgentGraphState,
  clock: GraphSmoothingClock,
  now = Date.now()
): { graph: AgentGraphState; resyncs: SmoothingResync[] } {
  const resyncs: SmoothingResync[] = []
  const nodes = { ...display.nodes }

  for (const nodeId of AGENT_NODE_IDS) {
    const target = logical.nodes[nodeId]
    const current = display.nodes[nodeId]
    const targetRank = nodeRank(target.status)
    const currentRank = nodeRank(current.status)

    if (target.status === "active" || target.status === "waiting") {
      clock.nodeActiveSince.set(nodeId, now)
      clock.nodeCompletedSince.delete(nodeId)
      nodes[nodeId] = target
      continue
    }

    if (target.status === "error") {
      clock.nodeActiveSince.delete(nodeId)
      clock.nodeCompletedSince.delete(nodeId)
      nodes[nodeId] = target
      continue
    }

    if (targetRank >= currentRank) {
      // Logical moved to completed/idle while display is still active — respect hold time.
      if (
        current.status === "active" &&
        (target.status === "completed" || target.status === "idle")
      ) {
        const holdMs = getNodeActiveHoldMs(nodeId)
        const since = clock.nodeActiveSince.get(nodeId) ?? now
        const elapsed = now - since

        if (elapsed < holdMs) {
          nodes[nodeId] = current
          resyncs.push({ delayMs: holdMs - elapsed })
          continue
        }
      }

      if (target.status === "completed") {
        clock.nodeCompletedSince.set(nodeId, now)
        clock.nodeActiveSince.delete(nodeId)
      }
      nodes[nodeId] = target
      continue
    }

    if (current.status === "waiting") {
      nodes[nodeId] = target
      clock.nodeActiveSince.delete(nodeId)
      clock.nodeCompletedSince.delete(nodeId)
      continue
    }

    if (current.status === "active") {
      const holdMs = getNodeActiveHoldMs(nodeId)
      const since = clock.nodeActiveSince.get(nodeId) ?? now
      const elapsed = now - since

      if (elapsed < holdMs) {
        nodes[nodeId] = current
        resyncs.push({ delayMs: holdMs - elapsed })
        continue
      }

      if (target.status === "completed") {
        clock.nodeCompletedSince.set(nodeId, now)
        clock.nodeActiveSince.delete(nodeId)
        nodes[nodeId] = target
        continue
      }

      const completed = toCompleted(current)
      clock.nodeCompletedSince.set(nodeId, now)
      clock.nodeActiveSince.delete(nodeId)
      nodes[nodeId] = completed
      resyncs.push({ delayMs: MIN_COMPLETED_VISIBLE_MS })
      continue
    }

    if (current.status === "completed") {
      const since = clock.nodeCompletedSince.get(nodeId) ?? now
      const elapsed = now - since

      if (target.status === "idle" && elapsed < MIN_COMPLETED_VISIBLE_MS) {
        nodes[nodeId] = current
        resyncs.push({ delayMs: MIN_COMPLETED_VISIBLE_MS - elapsed })
        continue
      }

      clock.nodeCompletedSince.delete(nodeId)
      nodes[nodeId] = target
      continue
    }

    nodes[nodeId] = target
  }

  const edges = smoothEdges(display.edges, logical.edges, clock, now, resyncs)

  return {
    graph: {
      ...logical,
      nodes,
      edges,
    },
    resyncs,
  }
}

function getEdgeActiveHoldMs(edge: GraphEdge): number {
  if (edge.from === "ticket_api" || edge.to === "ticket_api") {
    return TICKET_SERVICE_ACTIVE_MS
  }
  return MIN_EDGE_VISIBLE_MS
}

function smoothEdges(
  displayEdges: GraphEdge[],
  logicalEdges: GraphEdge[],
  clock: GraphSmoothingClock,
  now: number,
  resyncs: SmoothingResync[]
): GraphEdge[] {
  return logicalEdges.map((targetEdge) => {
    const currentEdge =
      displayEdges.find((edge) => edge.id === targetEdge.id) ?? targetEdge
    const targetRank = edgeRank(targetEdge.status)
    const currentRank = edgeRank(currentEdge.status)

    if (targetEdge.status === "active") {
      clock.edgeLitSince.set(targetEdge.id, now)
      return targetEdge
    }

    if (targetRank >= currentRank) {
      if (targetEdge.status === "completed") {
        clock.edgeLitSince.set(targetEdge.id, now)
      }
      return targetEdge
    }

    if (currentEdge.status === "active") {
      const holdMs = getEdgeActiveHoldMs(targetEdge)
      const since = clock.edgeLitSince.get(targetEdge.id) ?? now
      const elapsed = now - since

      if (elapsed < holdMs) {
        resyncs.push({ delayMs: holdMs - elapsed })
        return currentEdge
      }

      if (targetEdge.status === "idle") {
        resyncs.push({ delayMs: MIN_COMPLETED_VISIBLE_MS / 2 })
        return { ...targetEdge, status: "completed" }
      }
    }

    if (currentEdge.status === "completed" && targetEdge.status === "idle") {
      const holdMs = getEdgeActiveHoldMs(targetEdge)
      const since = clock.edgeLitSince.get(targetEdge.id) ?? now
      const elapsed = now - since

      if (elapsed < holdMs) {
        resyncs.push({ delayMs: holdMs - elapsed })
        return currentEdge
      }

      clock.edgeLitSince.delete(targetEdge.id)
    }

    return targetEdge
  })
}

export function minResyncDelay(resyncs: SmoothingResync[]): number | null {
  if (resyncs.length === 0) return null
  return Math.min(...resyncs.map((item) => item.delayMs))
}
