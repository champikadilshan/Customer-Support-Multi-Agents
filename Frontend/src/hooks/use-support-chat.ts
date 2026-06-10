"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { type Message } from "@/components/ui/chat-message"
import { useAgentTrace } from "@/hooks/use-agent-trace"
import { refreshTicketsPanel } from "@/hooks/use-tickets"
import {
  ChatApiError,
  getSession,
  postChat,
} from "@/lib/chat-api"
import {
  hitlPendingToRequest,
  type HitlPending,
} from "@/lib/hitl"
import {
  clearStoredSessionId,
  persistSessionId,
  readStoredSessionId,
} from "@/lib/session-storage"
import { consumeSseStream, type SseEvent } from "@/lib/sse"

export type { HitlRequest, HitlPending } from "@/lib/hitl"

function createId() {
  return crypto.randomUUID()
}

function createSystemMessage(content: string): Message {
  return {
    id: createId(),
    role: "system",
    content,
    createdAt: new Date(),
  }
}

export function useSupportChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isResetting, setIsResetting] = useState(false)
  const [isRestoringSession, setIsRestoringSession] = useState(true)
  const [activeAgent, setActiveAgent] = useState<string | null>(null)
  const [hitlPending, setHitlPending] = useState<HitlPending | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const { agentGraph, resetGraph, connectTrace, replayTrace } = useAgentTrace(sessionId)
  const abortRef = useRef<AbortController | null>(null)
  const hitlMessageIdRef = useRef<string | null>(null)

  const isHitlPending = hitlPending !== null

  const isGraphLive = useMemo(() => {
    if (isLoading || isHitlPending) return true
    return Object.values(agentGraph.nodes).some(
      (node) => node.status === "active" || node.status === "waiting"
    )
  }, [agentGraph.nodes, isHitlPending, isLoading])

  const refreshActiveAgent = useCallback(async (sid: string) => {
    try {
      const info = await getSession(sid)
      setActiveAgent(info.active_agent)
    } catch {
      // Non-fatal — badge stays as-is
    }
  }, [])

  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      const storedId = readStoredSessionId()
      if (!storedId) {
        setIsRestoringSession(false)
        return
      }

      try {
        const info = await getSession(storedId)
        if (cancelled) return

        setSessionId(storedId)
        setActiveAgent(info.active_agent)
        connectTrace(storedId)

        const pendingRequestId = info.metadata?.hitl_pending_request_id
        const ticketData = info.metadata?.hitl_ticket_data

        if (
          typeof pendingRequestId === "string" &&
          ticketData &&
          typeof ticketData === "object"
        ) {
          setHitlPending({
            request_id: pendingRequestId,
            ticket_preview: ticketData as HitlPending["ticket_preview"],
            hitl_question:
              "A ticket is awaiting your confirmation. Please choose an option below.",
            hitl_options: ["Yes, raise it", "No, skip it"],
          })
        }
      } catch (error) {
        if (cancelled) return
        if (error instanceof ChatApiError && error.status === 404) {
          clearStoredSessionId()
          setSessionId(null)
        }
      } finally {
        if (!cancelled) setIsRestoringSession(false)
      }
    }

    void restoreSession()

    return () => {
      cancelled = true
    }
  }, [connectTrace])

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(event.target.value)
    },
    []
  )

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsLoading(false)
  }, [])

  const appendMessage = useCallback((message: Message) => {
    setMessages((current) => [...current, message])
  }, [])

  const updateMessage = useCallback(
    (messageId: string, updater: (message: Message) => Message) => {
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId ? updater(message) : message
        )
      )
    },
    []
  )

  const clearLocalChatState = useCallback(() => {
    setMessages([])
    setInput("")
    setActiveAgent(null)
    setHitlPending(null)
    hitlMessageIdRef.current = null
    setSessionId(null)
    clearStoredSessionId()
    resetGraph()
  }, [resetGraph])

  const handleResumeEvent = useCallback(
    (assistantId: string, event: SseEvent) => {
      switch (event.type) {
        case "token":
          updateMessage(assistantId, (message) => ({
            ...message,
            content: message.content + event.data.text,
          }))
          break

        case "tool_call":
          updateMessage(assistantId, (message) => {
            const existing = message.toolInvocations ?? []
            return {
              ...message,
              toolInvocations: [
                ...existing,
                { state: "call" as const, toolName: event.data.tool },
              ],
            }
          })
          break

        case "error":
          appendMessage(
            createSystemMessage(
              event.data.message || "Something went wrong. Please try again."
            )
          )
          setHitlPending(null)
          hitlMessageIdRef.current = null
          break

        case "done":
          setHitlPending(null)
          hitlMessageIdRef.current = null
          refreshTicketsPanel()
          void refreshActiveAgent(sessionId ?? "")
          break
      }
    },
    [appendMessage, refreshActiveAgent, sessionId, updateMessage]
  )

  const sendMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim()
      if (!trimmed || isLoading || isHitlPending || isResetting || isRestoringSession) {
        return
      }

      const userMessage: Message = {
        id: createId(),
        role: "user",
        content: trimmed,
        createdAt: new Date(),
      }

      const assistantId = createId()
      const loadingAssistant: Message = {
        id: assistantId,
        role: "assistant",
        content: "",
        createdAt: new Date(),
      }

      setMessages((current) => [...current, userMessage, loadingAssistant])
      setInput("")
      setIsLoading(true)

      if (sessionId) {
        connectTrace(sessionId)
      }

      try {
        const data = await postChat(trimmed, sessionId)

        persistSessionId(data.session_id)
        setSessionId(data.session_id)
        connectTrace(data.session_id)

        if (data.hitl_pending && data.request_id) {
          const pending: HitlPending = {
            request_id: data.request_id,
            ticket_preview: data.ticket_preview ?? {},
            hitl_question: data.hitl_question ?? "Please confirm to continue.",
            hitl_options: data.hitl_options ?? ["Yes, raise it", "No, skip it"],
          }

          setHitlPending(pending)
          hitlMessageIdRef.current = assistantId

          const assistantContent =
            data.hitl_question?.trim() ||
            data.response?.trim() ||
            "Please review the ticket details below."

          updateMessage(assistantId, (message) => ({
            ...message,
            content: assistantContent,
            hitlRequest: hitlPendingToRequest(pending),
          }))
        } else {
          updateMessage(assistantId, (message) => ({
            ...message,
            content:
              data.response?.trim() ||
              "I was unable to generate a response. Please try again.",
          }))
        }

        void refreshActiveAgent(data.session_id)
      } catch (error) {
        setMessages((current) => current.filter((message) => message.id !== assistantId))

        if (error instanceof ChatApiError) {
          appendMessage(
            createSystemMessage("Something went wrong. Please try again.")
          )
        } else {
          appendMessage(
            createSystemMessage(
              "Connection lost. Please check your connection."
            )
          )
        }
      } finally {
        setIsLoading(false)
      }
    },
    [
      appendMessage,
      connectTrace,
      isHitlPending,
      isLoading,
      isResetting,
      isRestoringSession,
      refreshActiveAgent,
      sessionId,
      updateMessage,
    ]
  )

  const handleSubmit = useCallback(
    (event?: { preventDefault?: () => void }) => {
      event?.preventDefault?.()
      void sendMessage(input)
    },
    [input, sendMessage]
  )

  const resetSession = useCallback(async () => {
    if (isLoading || isHitlPending || isResetting) return

    stop()
    setIsResetting(true)

    try {
      if (sessionId) {
        const response = await fetch("/api/session/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId }),
        })

        if (!response.ok) {
          throw new Error("Failed to reset session")
        }
      }

      clearLocalChatState()
      toast.success("New conversation started")
    } catch {
      toast.error("Could not start a new conversation")
    } finally {
      setIsResetting(false)
    }
  }, [clearLocalChatState, isHitlPending, isLoading, isResetting, sessionId, stop])

  const respondToHitl = useCallback(
    async (messageId: string, response: "yes" | "no") => {
      if (!hitlPending || isLoading) return

      const requestId = hitlPending.request_id

      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? { ...message, hitlResponse: response }
            : message
        )
      )

      const resumeAssistantId = createId()
      appendMessage({
        id: resumeAssistantId,
        role: "assistant",
        content: "",
        createdAt: new Date(),
        toolInvocations: [],
      })

      setIsLoading(true)

      if (sessionId) {
        connectTrace(sessionId)
      }

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await consumeSseStream(
          "/api/chat/resume",
          { request_id: requestId, hitl_response: response },
          (event) => handleResumeEvent(resumeAssistantId, event),
          controller.signal
        )
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          appendMessage(
            createSystemMessage(
              "Connection lost. Please check your connection."
            )
          )
          setHitlPending(null)
          hitlMessageIdRef.current = null
        }
      } finally {
        abortRef.current = null
        setIsLoading(false)
      }
    },
    [
      appendMessage,
      connectTrace,
      handleResumeEvent,
      hitlPending,
      isLoading,
      sessionId,
    ]
  )

  return {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    stop,
    resetSession,
    isGenerating: isLoading,
    isLoading,
    isResetting,
    isRestoringSession,
    isHitlPending,
    hitlPending,
    activeAgent,
    respondToHitl,
    agentGraph,
    isGraphLive,
    sessionId,
    replayTrace,
  }
}
