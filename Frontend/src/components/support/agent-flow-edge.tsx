"use client"

import { memo, useMemo } from "react"
import {
  getSmoothStepPath,
  useInternalNode,
  type EdgeProps,
} from "@xyflow/react"

import type { TraceEdgeData } from "@/lib/agent-flow-elements"

type PathSegment = {
  d: string
  key: string
}

function buildSegmentedCollabPaths(
  source: string,
  target: string,
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  complaintLeftX: number,
  complaintRightX: number
): PathSegment[] {
  const billingToSales = source === "billing" && target === "sales"
  const salesToBilling = source === "sales" && target === "billing"
  if (!billingToSales && !salesToBilling) return []

  if (billingToSales) {
    return [
      {
        key: "before",
        d: `M ${sourceX},${sourceY} L ${complaintLeftX},${sourceY}`,
      },
      {
        key: "after",
        d: `M ${complaintRightX},${sourceY} L ${targetX},${targetY}`,
      },
    ]
  }

  return [
    {
      key: "before",
      d: `M ${sourceX},${sourceY} L ${complaintRightX},${sourceY}`,
    },
    {
      key: "after",
      d: `M ${complaintLeftX},${sourceY} L ${targetX},${targetY}`,
    },
  ]
}

function TraceEdgeComponent({
  id,
  source,
  target,
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
  const complaintNode = useInternalNode("complaint")
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

  const paths = useMemo(() => {
    if (!isCollab || !complaintNode?.internals.positionAbsolute) {
      return [{ key: "full", d: path }]
    }

    const leftX = complaintNode.internals.positionAbsolute.x
    const width = complaintNode.measured.width ?? 210
    const rightX = leftX + width

    const segmented = buildSegmentedCollabPaths(
      source,
      target,
      sourceX,
      sourceY,
      targetX,
      targetY,
      leftX,
      rightX
    )

    return segmented.length > 0 ? segmented : [{ key: "full", d: path }]
  }, [
    complaintNode,
    isCollab,
    path,
    source,
    target,
    sourceX,
    sourceY,
    targetX,
    targetY,
  ])

  if (!visible) return null

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
  const activeDasharray = isCollab ? "8 6" : "10 8"
  const dashOffset = isCollab ? "-28" : "-36"

  return (
    <g opacity={opacity}>
      {paths.map((segment) => (
        <path
          key={`${id}-${segment.key}`}
          d={segment.d}
          fill="none"
          stroke={stroke}
          strokeWidth={isActive ? (isCollab ? 2.5 : 3) : isCollab ? 1.75 : 2}
          strokeDasharray={isActive ? activeDasharray : idleDasharray}
          strokeLinecap="round"
          className="transition-[stroke,stroke-width,opacity] duration-300 ease-out"
        >
          {isActive ? (
            <animate
              attributeName="stroke-dashoffset"
              from="0"
              to={dashOffset}
              dur="0.8s"
              repeatCount="indefinite"
            />
          ) : null}
        </path>
      ))}
      {isActive
        ? paths.map((segment) => (
            <circle
              key={`${id}-flow-${segment.key}`}
              r={isCollab ? 3.5 : 4}
              fill={stroke}
              pointerEvents="none"
            >
              <animateMotion
                dur="0.8s"
                repeatCount="indefinite"
                path={segment.d}
              />
            </circle>
          ))
        : null}
    </g>
  )
}

export const TraceEdge = memo(TraceEdgeComponent)
