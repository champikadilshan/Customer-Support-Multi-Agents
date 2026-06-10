"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { createInitialAgentGraphState } from "@/lib/agent-graph"
import {
  connectAgentTrace,
  fetchTraceReplay,
  reduceAgentGraphOnTraceEvent,
  type TraceEvent,
} from "@/lib/trace"
import {
  createGraphSmoothingClock,
  minResyncDelay,
  smoothGraphDisplay,
} from "@/lib/trace-graph-smoothing"

export function useAgentTrace(sessionId: string | null) {
  const [agentGraph, setAgentGraph] = useState(createInitialAgentGraphState)
  const abortRef = useRef<AbortController | null>(null)
  const replayAbortRef = useRef(false)
  const logicalGraphRef = useRef(createInitialAgentGraphState())
  const smoothingClockRef = useRef(createGraphSmoothingClock())
  const resyncTimerRef = useRef<number | null>(null)

  const clearResyncTimer = useCallback(() => {
    if (resyncTimerRef.current != null) {
      window.clearTimeout(resyncTimerRef.current)
      resyncTimerRef.current = null
    }
  }, [])

  const scheduleResync = useCallback(
    (delayMs: number) => {
      clearResyncTimer()
      resyncTimerRef.current = window.setTimeout(() => {
        resyncTimerRef.current = null
        setAgentGraph((display) => {
          const { graph, resyncs } = smoothGraphDisplay(
            display,
            logicalGraphRef.current,
            smoothingClockRef.current
          )
          const nextDelay = minResyncDelay(resyncs)
          if (nextDelay != null) {
            scheduleResync(nextDelay)
          }
          return graph
        })
      }, delayMs)
    },
    [clearResyncTimer]
  )

  const syncDisplayFromLogical = useCallback(
    (display: typeof agentGraph) => {
      const { graph, resyncs } = smoothGraphDisplay(
        display,
        logicalGraphRef.current,
        smoothingClockRef.current
      )
      const delay = minResyncDelay(resyncs)
      if (delay != null) {
        scheduleResync(delay)
      }
      return graph
    },
    [scheduleResync]
  )

  const applyTraceEvent = useCallback(
    (event: TraceEvent) => {
      logicalGraphRef.current = reduceAgentGraphOnTraceEvent(
        logicalGraphRef.current,
        event
      )
      setAgentGraph((display) => syncDisplayFromLogical(display))
    },
    [syncDisplayFromLogical]
  )

  const clearSmoothing = useCallback(() => {
    clearResyncTimer()
    smoothingClockRef.current = createGraphSmoothingClock()
  }, [clearResyncTimer])

  const resetGraph = useCallback(() => {
    clearSmoothing()
    logicalGraphRef.current = createInitialAgentGraphState()
    setAgentGraph(createInitialAgentGraphState())
  }, [clearSmoothing])

  const connectTrace = useCallback(
    (sid: string) => {
      abortRef.current?.abort()

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

      clearSmoothing()
      logicalGraphRef.current = createInitialAgentGraphState()
      setAgentGraph(createInitialAgentGraphState())

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
    [applyTraceEvent, clearSmoothing, connectTrace]
  )

  useEffect(() => {
    if (!sessionId) {
      abortRef.current?.abort()
      abortRef.current = null
      return
    }

    connectTrace(sessionId)

    return () => {
      abortRef.current?.abort()
      replayAbortRef.current = true
      clearSmoothing()
    }
  }, [sessionId, clearSmoothing, connectTrace])

  return {
    agentGraph,
    resetGraph,
    connectTrace,
    replayTrace,
  }
}

export { SESSION_STORAGE_KEY, readStoredSessionId } from "@/lib/session-storage"
