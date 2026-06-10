import type { Edge, Node } from "@xyflow/react"

import {
  AGENT_NODE_IDS,
  getEdgeStatus,
  NODE_KIND,
  type AgentGraphState,
  type AgentNodeId,
  type EdgeStatus,
  type NodeStatus,
} from "@/lib/agent-graph"
import type { HealthStatus } from "@/hooks/use-agent-health"
import {
  mapHandoffToNodeId,
  NODE_LAYOUT,
  STATIC_EDGES,
  type StaticEdge,
} from "@/lib/agent-flow-layout"

export type AgentFlowNodeData = {
  nodeId: AgentNodeId
  status: NodeStatus
  detail?: string
  runningTool?: string
  dimmed: boolean
  highlighted: boolean
  health?: HealthStatus
  kind: "orchestrator" | "agent" | "infra"
}

export type TraceEdgeData = {
  kind: StaticEdge["kind"]
  status: EdgeStatus
  visible: boolean
}

function getStaticEdgeStatus(
  graph: AgentGraphState,
  edge: StaticEdge
): EdgeStatus {
  return getEdgeStatus(graph, edge.from, edge.to)
}

function isAgentDimmed(graph: AgentGraphState, nodeId: AgentNodeId) {
  const kind = NODE_KIND[nodeId]
  if (kind !== "agent") return false

  return (
    graph.routedAgent !== nodeId &&
    Boolean(graph.routedAgent) &&
    graph.nodes[nodeId].status === "idle"
  )
}

export function buildFlowNodes(
  graph: AgentGraphState,
  options?: {
    highlightNodeId?: AgentNodeId | null
    health?: Partial<Record<AgentNodeId, HealthStatus>>
  }
): Node<AgentFlowNodeData>[] {
  return AGENT_NODE_IDS.map((nodeId) => {
    const layout = NODE_LAYOUT[nodeId]
    const node = graph.nodes[nodeId]

    return {
      id: nodeId,
      type: "agentFlow",
      position: { x: layout.x, y: layout.y },
      data: {
        nodeId,
        status: node.status,
        detail: node.detail,
        runningTool: node.runningTools.at(-1),
        dimmed: isAgentDimmed(graph, nodeId),
        highlighted: options?.highlightNodeId === nodeId,
        health: options?.health?.[nodeId],
        kind: NODE_KIND[nodeId],
      },
      style: {
        width: layout.w,
        height: layout.h,
      },
      draggable: false,
      selectable: false,
      connectable: false,
      zIndex: 1,
    }
  })
}

export function buildFlowEdges(graph: AgentGraphState): Edge<TraceEdgeData>[] {
  const staticEdges: Edge<TraceEdgeData>[] = STATIC_EDGES.map((edge) => {
    const status = getStaticEdgeStatus(graph, edge)
    const visible = true

    return {
      id: edge.id,
      source: edge.from,
      target: edge.to,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
      type: "trace",
      zIndex: 0,
      data: {
        kind: edge.kind,
        status,
        visible,
      },
      selectable: false,
      focusable: false,
    }
  })

  const dynamicHandoffs: Edge<TraceEdgeData>[] = graph.handoffs
    .map((handoff) => {
      const from = mapHandoffToNodeId(handoff.from)
      const to = mapHandoffToNodeId(handoff.to)
      if (!from || !to || from === to) return null
      if (handoff.status === "idle") return null

      const hasStaticEdge = STATIC_EDGES.some(
        (edge) => edge.from === from && edge.to === to
      )
      if (hasStaticEdge) return null

      return {
        id: `handoff-${handoff.from}-${handoff.to}`,
        source: from,
        target: to,
        sourceHandle: "right",
        targetHandle: "left",
        type: "trace",
        zIndex: 0,
        data: {
          kind: "collaboration" as const,
          status: handoff.status,
          visible: true,
        },
        selectable: false,
        focusable: false,
      }
    })
    .filter(Boolean) as Edge<TraceEdgeData>[]

  return [...staticEdges, ...dynamicHandoffs]
}
