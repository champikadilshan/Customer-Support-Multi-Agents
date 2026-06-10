"use client"

import { useCallback, useMemo, useRef, useState } from "react"
import { toast } from "sonner"

import { type Message } from "@/components/ui/chat-message"
import { useAgentTrace, readStoredSessionId, SESSION_STORAGE_KEY } from "@/hooks/use-agent-trace"
import { refreshTicketsPanel } from "@/hooks/use-tickets"
import { consumeSseStream, type SseEvent } from "@/lib/sse"

export type { HitlRequest } from "@/lib/hitl"

function createId() {
  return crypto.randomUUID()
}

function persistSessionId(sessionId: string) {
  localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
}

export function useSupportChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [isResetting, setIsResetting] = useState(false)
  const [activeAgent, setActiveAgent] = useState<string | null>(null)
  const [activeIntent, setActiveIntent] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(readStoredSessionId)
  const { agentGraph, resetGraph, connectTrace, replayTrace } = useAgentTrace(sessionId)
  const abortRef = useRef<AbortController | null>(null)
  const assistantIdRef = useRef<string | null>(null)

  const isHitlPending = useMemo(
    () => messages.some((message) => message.hitlRequest && !message.hitlResponse),
    [messages]
  )

  const isGraphLive = useMemo(() => {
    if (isGenerating || isHitlPending) return true

    return Object.values(agentGraph.nodes).some(
      (node) => node.status === "active" || node.status === "waiting"
    )
  }, [agentGraph.nodes, isGenerating, isHitlPending])

  const handleInputChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(event.target.value)
    },
    []
  )

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsGenerating(false)
  }, [])

  const clearLocalChatState = useCallback(() => {
    setMessages([])
    setInput("")
    setActiveAgent(null)
    setActiveIntent(null)
    resetGraph()
  }, [resetGraph])

  const updateAssistantMessage = useCallback(
    (assistantId: string, updater: (message: Message) => Message) => {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? updater(message) : message
        )
      )
    },
    []
  )

  const handleStreamEvent = useCallback(
    (assistantId: string, event: SseEvent) => {
      switch (event.type) {
        case "session": {
          const sid = event.data.session_id
          persistSessionId(sid)
          setSessionId(sid)
          connectTrace(sid)
          break
        }

        case "intent":
          setActiveIntent(event.data.intent)
          setActiveAgent(event.data.agent)
          break

        case "tool_call":
          updateAssistantMessage(assistantId, (message) => {
            const existing = message.toolInvocations ?? []
            const completed = existing.map((tool) =>
              tool.state === "call"
                ? {
                    state: "result" as const,
                    toolName: tool.toolName,
                    result: { completed: true },
                  }
                : tool
            )

            return {
              ...message,
              toolInvocations: [
                ...completed,
                { state: "call" as const, toolName: event.data.tool },
              ],
            }
          })
          break

        case "token":
          updateAssistantMessage(assistantId, (message) => ({
            ...message,
            content: message.content + event.data.text,
          }))
          break

        case "hitl_request":
          updateAssistantMessage(assistantId, (message) => ({
            ...message,
            hitlRequest: event.data,
          }))
          break

        case "error":
          updateAssistantMessage(assistantId, (message) => ({
            ...message,
            content: message.content || event.data.message,
          }))
          break

        case "done":
          updateAssistantMessage(assistantId, (message) => {
            const completedTools = message.toolInvocations?.map((tool) =>
              tool.state === "call"
                ? {
                    state: "result" as const,
                    toolName: tool.toolName,
                    result: { completed: true },
                  }
                : tool
            )

            return {
              ...message,
              toolInvocations: completedTools,
            }
          })
          refreshTicketsPanel()
          break
      }
    },
    [connectTrace, updateAssistantMessage]
  )

  const streamMessage = useCallback(
    async (message: string, url = "/api/chat/stream") => {
      const userMessage: Message = {
        id: createId(),
        role: "user",
        content: message,
        createdAt: new Date(),
      }

      const assistantId = createId()
      assistantIdRef.current = assistantId
      const assistantMessage: Message = {
        id: assistantId,
        role: "assistant",
        content: "",
        createdAt: new Date(),
        toolInvocations: [],
      }

      setMessages((current) => [...current, userMessage, assistantMessage])
      setActiveAgent(null)
      setActiveIntent(null)
      setIsGenerating(true)

      if (sessionId) {
        connectTrace(sessionId)
      }

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await consumeSseStream(
          url,
          {
            message,
            session_id: sessionId,
          },
          (event) => handleStreamEvent(assistantId, event),
          controller.signal
        )
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          updateAssistantMessage(assistantId, (current) => ({
            ...current,
            content:
              current.content ||
              "Something went wrong while contacting support. Please try again.",
          }))
        }
      } finally {
        abortRef.current = null
        setIsGenerating(false)
      }
    },
    [connectTrace, handleStreamEvent, sessionId, updateAssistantMessage]
  )

  const sendMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim()
      if (!trimmed || isGenerating || isHitlPending || isResetting) return

      setInput("")
      await streamMessage(trimmed)
    },
    [isGenerating, isHitlPending, isResetting, streamMessage]
  )

  const handleSubmit = useCallback(
    (event?: { preventDefault?: () => void }) => {
      event?.preventDefault?.()
      void sendMessage(input)
    },
    [input, sendMessage]
  )

  const resetSession = useCallback(async () => {
    if (isGenerating || isHitlPending || isResetting) return

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
      toast.success("Chat session reset")
    } catch {
      toast.error("Could not reset the chat session")
    } finally {
      setIsResetting(false)
    }
  }, [clearLocalChatState, isGenerating, isHitlPending, isResetting, sessionId, stop])

  const respondToHitl = useCallback(
    async (messageId: string, response: "yes" | "no") => {
      const targetMessage = messages.find((message) => message.id === messageId)
      if (!targetMessage?.hitlRequest || targetMessage.hitlResponse) return

      const requestId = targetMessage.hitlRequest.request_id
      assistantIdRef.current = messageId

      setMessages((current) =>
        current.map((message) =>
          message.id === messageId
            ? { ...message, hitlResponse: response }
            : message
        )
      )
      setIsGenerating(true)

      if (sessionId) {
        connectTrace(sessionId)
      }

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await consumeSseStream(
          "/api/chat/resume",
          { request_id: requestId, hitl_response: response },
          (event) => handleStreamEvent(messageId, event),
          controller.signal
        )
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          updateAssistantMessage(messageId, (current) => ({
            ...current,
            content:
              current.content ||
              "Failed to resume the complaint flow. Please try your request again.",
          }))
        }
      } finally {
        abortRef.current = null
        setIsGenerating(false)
      }
    },
    [connectTrace, handleStreamEvent, messages, sessionId, updateAssistantMessage]
  )

  return {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    stop,
    resetSession,
    isGenerating,
    isResetting,
    isHitlPending,
    activeAgent,
    activeIntent,
    respondToHitl,
    agentGraph,
    isGraphLive,
    sessionId,
    replayTrace,
  }
}
