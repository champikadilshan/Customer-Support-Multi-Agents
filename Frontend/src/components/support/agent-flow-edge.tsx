"use client"

import { memo } from "react"
import {
  BaseEdge,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react"

import type { TraceEdgeData } from "@/lib/agent-flow-elements"

function TraceEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const kind = (data as TraceEdgeData | undefined)?.kind ?? "route"
  const status = (data as TraceEdgeData | undefined)?.status ?? "idle"
  const visible = (data as TraceEdgeData | undefined)?.visible !== false

  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 14,
    offset: kind === "collaboration" ? 24 : kind === "route" ? 8 : 4,
  })

  const isActive = status === "active"
  const isCompleted = status === "completed"
  const isData = kind === "data"

  let stroke = "hsl(var(--border))"
  if (isActive) {
    stroke = isData ? "rgb(5 150 105)" : "hsl(var(--foreground))"
  } else if (isCompleted) {
    stroke = isData ? "rgba(5, 150, 105, 0.45)" : "hsl(var(--foreground) / 0.35)"
  }

  const strokeDasharray =
    kind === "collaboration" ? "6 6" : kind === "data" ? "4 5" : undefined

  return (
    <g opacity={visible ? 1 : 0.28}>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke,
          strokeWidth: isActive ? 3 : 2,
          strokeDasharray,
          strokeLinecap: "round",
          transition: "stroke 0.35s ease, stroke-width 0.35s ease, opacity 0.35s ease",
        }}
      />
      {isActive ? (
        <circle r="4" fill={stroke}>
          <animateMotion dur="0.8s" repeatCount="1" path={path} />
        </circle>
      ) : null}
    </g>
  )
}

export const TraceEdge = memo(TraceEdgeComponent)
