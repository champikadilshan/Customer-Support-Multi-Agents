"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import {
  createInitialAgentGraphState,
} from "@/lib/agent-graph"
import {
  connectAgentTrace,
  reduceAgentGraphOnTraceEvent,
  type TraceEvent,
} from "@/lib/trace"

const SESSION_STORAGE_KEY = "support-chat-session-id"

function readStoredSessionId() {
  if (typeof window === "undefined") return null
  return localStorage.getItem(SESSION_STORAGE_KEY)
}

export function useAgentTrace(sessionId: string | null) {
  const [agentGraph, setAgentGraph] = useState(createInitialAgentGraphState)
  const abortRef = useRef<AbortController | null>(null)
  const sessionRef = useRef<string | null>(null)

  const applyTraceEvent = useCallback((event: TraceEvent) => {
    setAgentGraph((current) => reduceAgentGraphOnTraceEvent(current, event))
  }, [])

  const resetGraph = useCallback(() => {
    setAgentGraph(createInitialAgentGraphState())
  }, [])

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
    }
  }, [sessionId, connectTrace])

  return {
    agentGraph,
    resetGraph,
    connectTrace,
  }
}

export { SESSION_STORAGE_KEY, readStoredSessionId }
