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
  if (edge.kind === "route" || edge.kind === "data" || edge.kind === "pipeline") {
    return getEdgeStatus(graph, edge.from, edge.to)
  }

  const handoff = graph.handoffs.find(
    (item) =>
      mapHandoffToNodeId(item.from) === edge.from &&
      mapHandoffToNodeId(item.to) === edge.to
  )

  return handoff?.status ?? "idle"
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

export function buildFlowNodes(graph: AgentGraphState): Node<AgentFlowNodeData>[] {
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
        kind: NODE_KIND[nodeId],
      },
      style: {
        width: layout.w,
        height: layout.h,
      },
      draggable: false,
      selectable: false,
      connectable: false,
    }
  })
}

export function buildFlowEdges(graph: AgentGraphState): Edge<TraceEdgeData>[] {
  const staticEdges: Edge<TraceEdgeData>[] = STATIC_EDGES.map((edge) => {
    const status = getStaticEdgeStatus(graph, edge)
    const isPipeline = edge.kind === "pipeline"
    const visible = !isPipeline || graph.showComplaintFlow

    return {
      id: edge.id,
      source: edge.from,
      target: edge.to,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
      type: "trace",
      data: {
        kind: edge.kind,
        status,
        visible,
      },
      animated: status === "active",
      selectable: false,
      focusable: false,
    }
  })

  const dynamicHandoffs: Edge<TraceEdgeData>[] = graph.handoffs
    .map((handoff) => {
      const from = mapHandoffToNodeId(handoff.from)
      const to = mapHandoffToNodeId(handoff.to)
      if (!from || !to || from === to) return null

      const isStaticCollab = STATIC_EDGES.some(
        (edge) =>
          edge.kind === "collaboration" && edge.from === from && edge.to === to
      )
      if (isStaticCollab) return null

      return {
        id: `handoff-${handoff.from}-${handoff.to}`,
        source: from,
        target: to,
        sourceHandle: "right",
        targetHandle: "left",
        type: "trace",
        data: {
          kind: "collaboration" as const,
          status: handoff.status,
          visible: true,
        },
        animated: handoff.status === "active",
        selectable: false,
        focusable: false,
      }
    })
    .filter(Boolean) as Edge<TraceEdgeData>[]

  return [...staticEdges, ...dynamicHandoffs]
}
