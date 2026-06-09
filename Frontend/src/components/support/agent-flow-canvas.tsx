"use client"

import { useEffect, useMemo, useRef } from "react"
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"

import { cn } from "@/lib/utils"
import { type AgentGraphState } from "@/lib/agent-graph"
import {
  buildFlowEdges,
  buildFlowNodes,
} from "@/lib/agent-flow-elements"
import { AgentFlowNode } from "@/components/support/agent-flow-node"
import { TraceEdge } from "@/components/support/agent-flow-edge"

const nodeTypes = { agentFlow: AgentFlowNode }
const edgeTypes = { trace: TraceEdge }

const FIT_VIEW_OPTIONS = { padding: 0.14, minZoom: 0.55, maxZoom: 1.1 }

type AgentFlowCanvasProps = {
  graph: AgentGraphState
  className?: string
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
}: AgentFlowCanvasProps & {
  containerRef: React.RefObject<HTMLDivElement | null>
}) {
  const nodes = useMemo(() => buildFlowNodes(graph), [graph])
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
      maxZoom={1.25}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      panOnDrag={false}
      zoomOnScroll={false}
      zoomOnPinch={false}
      zoomOnDoubleClick={false}
      preventScrolling={false}
      proOptions={{ hideAttribution: true }}
      className="agent-flow-canvas h-full w-full"
    >
      <FitViewOnResize containerRef={containerRef} />
      <Background
        variant={BackgroundVariant.Dots}
        gap={18}
        size={1}
        color="hsl(var(--border))"
      />
    </ReactFlow>
  )
}

export function AgentFlowCanvas({ graph, className }: AgentFlowCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)

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
          <AgentFlowGraph graph={graph} containerRef={containerRef} />
        </div>
      </ReactFlowProvider>
    </div>
  )
}
