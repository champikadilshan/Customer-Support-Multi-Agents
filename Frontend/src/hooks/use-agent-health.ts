"use client"

import { useCallback, useEffect, useState } from "react"

import type { AgentNodeId } from "@/lib/agent-graph"

export type HealthStatus = "healthy" | "down" | "unknown"

export type NodeHealthMap = Partial<Record<AgentNodeId, HealthStatus>>

const HEALTH_POLL_MS = 30_000

const HEALTH_TARGETS: { nodeId: AgentNodeId; url: string }[] = [
  { nodeId: "intent_detector", url: "/api/health/orchestrator" },
  { nodeId: "billing", url: "/api/health/billing" },
  { nodeId: "complaint", url: "/api/health/complaint" },
  { nodeId: "sales", url: "/api/health/sales" },
  { nodeId: "ticket_api", url: "/api/health/ticket" },
  { nodeId: "sales_mcp", url: "/api/health/mcp" },
]

async function checkHealth(url: string): Promise<HealthStatus> {
  try {
    const response = await fetch(url, { cache: "no-store" })
    const payload = (await response.json()) as { status?: string }
    if (payload.status === "unknown") return "unknown"
    if (!response.ok) return "down"
    return payload.status === "ok" ? "healthy" : "down"
  } catch {
    return "down"
  }
}

export function useAgentHealth() {
  const [health, setHealth] = useState<NodeHealthMap>({})

  const refresh = useCallback(async () => {
    const results = await Promise.all(
      HEALTH_TARGETS.map(async ({ nodeId, url }) => ({
        nodeId,
        status: await checkHealth(url),
      }))
    )

    setHealth(
      Object.fromEntries(results.map(({ nodeId, status }) => [nodeId, status]))
    )
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => {
      void refresh()
    }, HEALTH_POLL_MS)

    return () => window.clearInterval(timer)
  }, [refresh])

  return { health, refresh }
}
