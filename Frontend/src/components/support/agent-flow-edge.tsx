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

  const idleDasharray =
    kind === "collaboration" ? "6 6" : kind === "data" ? "4 5" : undefined

  return (
    <g>
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={isActive ? 3 : 2}
        strokeDasharray={isActive ? "10 8" : idleDasharray}
        strokeLinecap="round"
        className="transition-[stroke,stroke-width,opacity] duration-300 ease-out"
      >
        {isActive ? (
          <animate
            attributeName="stroke-dashoffset"
            from="0"
            to="-36"
            dur="0.8s"
            repeatCount="indefinite"
          />
        ) : null}
      </path>
      {isActive ? (
        <circle r="4" fill={stroke} pointerEvents="none">
          <animateMotion dur="0.8s" repeatCount="indefinite" path={path} />
        </circle>
      ) : null}
    </g>
  )
}

export const TraceEdge = memo(TraceEdgeComponent)
