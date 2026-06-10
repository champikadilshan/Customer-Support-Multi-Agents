"use client"

import { useEffect, useMemo, useRef } from "react"
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"

import { cn } from "@/lib/utils"
import { type AgentGraphState, type AgentNodeId } from "@/lib/agent-graph"
import {
  buildFlowEdges,
  buildFlowNodes,
} from "@/lib/agent-flow-elements"
import { AgentFlowNode } from "@/components/support/agent-flow-node"
import { TraceEdge } from "@/components/support/agent-flow-edge"
import { useAgentHealth } from "@/hooks/use-agent-health"

const nodeTypes = { agentFlow: AgentFlowNode }
const edgeTypes = { trace: TraceEdge }

const FIT_VIEW_OPTIONS = { padding: 0.02, minZoom: 0.78, maxZoom: 1.75 }

type AgentFlowCanvasProps = {
  graph: AgentGraphState
  className?: string
  highlightNodeId?: AgentNodeId | null
}

function FitViewOnResize({ containerRef }: { containerRef: React.RefObject<HTMLDivElement | null> }) {
  const { fitView } = useReactFlow()

  useEffect(() => {
    const runFit = () => {
      requestAnimationFrame(() => {
        void fitView(FIT_VIEW_OPTIONS)
      })
    }

    runFit()
    window.addEventListener("resize", runFit)

    const container = containerRef.current
    const observer =
      container && typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(runFit)
        : null

    if (container && observer) {
      observer.observe(container)
    }

    return () => {
      window.removeEventListener("resize", runFit)
      observer?.disconnect()
    }
  }, [containerRef, fitView])

  return null
}

function AgentFlowGraph({
  graph,
  containerRef,
  highlightNodeId,
  health,
}: AgentFlowCanvasProps & {
  containerRef: React.RefObject<HTMLDivElement | null>
  health: ReturnType<typeof useAgentHealth>["health"]
}) {
  const nodes = useMemo(
    () => buildFlowNodes(graph, { highlightNodeId, health }),
    [graph, highlightNodeId, health]
  )
  const edges = useMemo(() => buildFlowEdges(graph), [graph])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      fitViewOptions={FIT_VIEW_OPTIONS}
      minZoom={0.5}
      maxZoom={2.5}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      panOnDrag
      panOnScroll={false}
      zoomOnScroll
      zoomOnPinch
      zoomOnDoubleClick
      zoomActivationKeyCode={null}
      preventScrolling
      proOptions={{ hideAttribution: true }}
      className="agent-flow-canvas h-full w-full"
    >
      <FitViewOnResize containerRef={containerRef} />
      <Controls
        showInteractive={false}
        position="bottom-right"
        className="agent-flow-controls !border-border !bg-background/95 !shadow-sm"
      />
      <Background
        variant={BackgroundVariant.Dots}
        gap={18}
        size={1}
        color="hsl(var(--border))"
      />
    </ReactFlow>
  )
}

export function AgentFlowCanvas({
  graph,
  className,
  highlightNodeId,
}: AgentFlowCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { health } = useAgentHealth()

  return (
    <div
      ref={containerRef}
      className={cn(
        "min-h-0 w-full overflow-hidden rounded-xl border bg-muted/15",
        className
      )}
    >
      <ReactFlowProvider>
        <div className="h-full w-full">
          <AgentFlowGraph
            graph={graph}
            containerRef={containerRef}
            highlightNodeId={highlightNodeId}
            health={health}
          />
        </div>
      </ReactFlowProvider>
    </div>
  )
}
