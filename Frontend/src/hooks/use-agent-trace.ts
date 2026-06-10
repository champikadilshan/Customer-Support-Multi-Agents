"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import {
  createInitialAgentGraphState,
  setNode,
  type AgentNodeId,
} from "@/lib/agent-graph"
import {
  connectAgentTrace,
  fetchTraceReplay,
  getFlashResetTargets,
  reduceAgentGraphOnTraceEvent,
  type TraceEvent,
} from "@/lib/trace"

const FLASH_RESET_MS = 1500

export function useAgentTrace(sessionId: string | null) {
  const [agentGraph, setAgentGraph] = useState(createInitialAgentGraphState)
  const abortRef = useRef<AbortController | null>(null)
  const sessionRef = useRef<string | null>(null)
  const flashTimersRef = useRef<Map<AgentNodeId, number>>(new Map())
  const replayAbortRef = useRef(false)

  const scheduleFlashReset = useCallback((nodeIds: AgentNodeId[]) => {
    for (const nodeId of nodeIds) {
      const existing = flashTimersRef.current.get(nodeId)
      if (existing) window.clearTimeout(existing)

      const timer = window.setTimeout(() => {
        flashTimersRef.current.delete(nodeId)
        setAgentGraph((current) => {
          if (current.nodes[nodeId].status !== "completed") return current

          let next = setNode(current, nodeId, "idle")
          next = {
            ...next,
            edges: next.edges.map((edge) =>
              (edge.from === nodeId || edge.to === nodeId) &&
              edge.status === "completed"
                ? { ...edge, status: "idle" }
                : edge
            ),
            handoffs: next.handoffs.map((handoff) =>
              handoff.status === "completed"
                ? { ...handoff, status: "idle" }
                : handoff
            ),
          }
          return next
        })
      }, FLASH_RESET_MS)

      flashTimersRef.current.set(nodeId, timer)
    }
  }, [])

  const applyTraceEvent = useCallback(
    (event: TraceEvent) => {
      setAgentGraph((current) => reduceAgentGraphOnTraceEvent(current, event))

      const flashTargets = getFlashResetTargets(event)
      if (flashTargets.length > 0) {
        scheduleFlashReset(flashTargets)
      }
    },
    [scheduleFlashReset]
  )

  const clearFlashTimers = useCallback(() => {
    flashTimersRef.current.forEach((timer) => window.clearTimeout(timer))
    flashTimersRef.current.clear()
  }, [])

  const resetGraph = useCallback(() => {
    clearFlashTimers()
    setAgentGraph(createInitialAgentGraphState())
  }, [clearFlashTimers])

  const connectTrace = useCallback(
    (sid: string) => {
      abortRef.current?.abort()

      sessionRef.current = sid
      const controller = new AbortController()
      abortRef.current = controller

      void connectAgentTrace(sid, applyTraceEvent, controller.signal)
        .catch(() => {
          if (abortRef.current === controller) {
            setAgentGraph((current) => ({ ...current, traceConnected: false }))
          }
        })
        .finally(() => {
          if (abortRef.current === controller) {
            abortRef.current = null
          }
        })
    },
    [applyTraceEvent]
  )

  const replayTrace = useCallback(
    async (sid: string) => {
      replayAbortRef.current = true
      abortRef.current?.abort()

      clearFlashTimers()
      resetGraph()

      try {
        const events = await fetchTraceReplay(sid)
        replayAbortRef.current = false

        for (const event of events) {
          if (replayAbortRef.current) break
          applyTraceEvent(event)
          await new Promise((resolve) => window.setTimeout(resolve, 150))
        }
      } catch {
        replayAbortRef.current = false
      } finally {
        if (!replayAbortRef.current) {
          connectTrace(sid)
        }
      }
    },
    [applyTraceEvent, clearFlashTimers, connectTrace, resetGraph]
  )

  useEffect(() => {
    if (!sessionId) {
      abortRef.current?.abort()
      abortRef.current = null
      sessionRef.current = null
      return
    }

    connectTrace(sessionId)

    return () => {
      abortRef.current?.abort()
      replayAbortRef.current = true
      clearFlashTimers()
    }
  }, [sessionId, clearFlashTimers, connectTrace])

  return {
    agentGraph,
    resetGraph,
    connectTrace,
    replayTrace,
  }
}

export { SESSION_STORAGE_KEY, readStoredSessionId } from "@/lib/session-storage"
