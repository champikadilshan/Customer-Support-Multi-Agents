"use client"

import { memo } from "react"
import {
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react"

import type { TraceEdgeData } from "@/lib/agent-flow-elements"

function TraceEdgeComponent({
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

  if (!visible) return null

  const isCollab = kind === "collaboration"

  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 14,
    offset: isCollab ? 24 : kind === "route" ? 8 : 4,
  })

  const isActive = status === "active"
  const isCompleted = status === "completed"
  const isData = kind === "data"

  let stroke = "hsl(var(--border))"
  let opacity = 1

  if (isCollab) {
    if (isActive) {
      stroke = "hsl(var(--foreground) / 0.7)"
      opacity = 1
    } else if (isCompleted) {
      stroke = "hsl(var(--foreground) / 0.35)"
      opacity = 0.85
    } else {
      stroke = "hsl(var(--muted-foreground) / 0.45)"
      opacity = 0.65
    }
  } else if (isActive) {
    stroke = isData ? "rgb(5 150 105)" : "hsl(var(--foreground))"
  } else if (isCompleted) {
    stroke = isData ? "rgba(5, 150, 105, 0.45)" : "hsl(var(--foreground) / 0.35)"
  }

  const idleDasharray = isCollab ? "6 6" : undefined

  return (
    <g opacity={opacity}>
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={isActive ? 3 : isCollab ? 1.75 : 2}
        strokeDasharray={isActive && !isCollab ? "10 8" : idleDasharray}
        strokeLinecap="round"
        className="transition-[stroke,stroke-width,opacity] duration-300 ease-out"
      >
        {isActive && !isCollab ? (
          <animate
            attributeName="stroke-dashoffset"
            from="0"
            to="-36"
            dur="0.8s"
            repeatCount="indefinite"
          />
        ) : null}
      </path>
      {isActive && !isCollab ? (
        <circle r="4" fill={stroke} pointerEvents="none">
          <animateMotion dur="0.8s" repeatCount="indefinite" path={path} />
        </circle>
      ) : null}
    </g>
  )
}

export const TraceEdge = memo(TraceEdgeComponent)
