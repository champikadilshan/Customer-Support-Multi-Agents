"use client"

import { useCallback, useRef, useState } from "react"

import { type Message } from "@/components/ui/chat-message"
import { refreshTicketsPanel } from "@/hooks/use-tickets"
import { consumeSseStream, type SseEvent } from "@/lib/sse"

export type HitlRequest = {
  request_id: string
  question: string
  ticket_preview: {
    title?: string
    category?: string
    priority?: string
  }
  options: string[]
}

const INITIAL_MESSAGES: Message[] = [
  {
    id: "demo-1",
    role: "user",
    content: "Do you need any help?",
  },
  {
    id: "demo-2",
    role: "assistant",
    content:
      "Customer support agent is an AI-powered platform. It routes your requests to billing, sales, or complaint specialists.",
  },
]

const SUPPORT_SUGGESTIONS = [
  "What is my current account balance?",
  "I want to raise a complaint about my recent order",
  "What laptops do you have under $1000?",
]

function createId() {
  return crypto.randomUUID()
}

export function useSupportChat() {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES)
  const [input, setInput] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [activeAgent, setActiveAgent] = useState<string | null>(null)
  const [activeIntent, setActiveIntent] = useState<string | null>(null)
  const [hitlRequest, setHitlRequest] = useState<HitlRequest | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const assistantIdRef = useRef<string | null>(null)

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
          setHitlRequest(event.data)
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
    [updateAssistantMessage]
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
      setHitlRequest(null)
      setIsGenerating(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await consumeSseStream(
          url,
          { message },
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
    [handleStreamEvent, updateAssistantMessage]
  )

  const sendMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim()
      if (!trimmed || isGenerating) return

      setInput("")
      await streamMessage(trimmed)
    },
    [isGenerating, streamMessage]
  )

  const handleSubmit = useCallback(
    (event?: { preventDefault?: () => void }) => {
      event?.preventDefault?.()
      void sendMessage(input)
    },
    [input, sendMessage]
  )

  const append = useCallback(
    (message: { role: "user"; content: string }) => {
      void sendMessage(message.content)
    },
    [sendMessage]
  )

  const respondToHitl = useCallback(
    async (response: "yes" | "no") => {
      if (!hitlRequest) return

      const requestId = hitlRequest.request_id
      setHitlRequest(null)
      setIsGenerating(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        await consumeSseStream(
          "/api/chat/resume",
          { request_id: requestId, hitl_response: response },
          (event) => {
            const assistantId = assistantIdRef.current
            if (assistantId) {
              handleStreamEvent(assistantId, event)
            }
          },
          controller.signal
        )
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          setMessages((current) => [
            ...current,
            {
              id: createId(),
              role: "assistant",
              content:
                "Failed to resume the complaint flow. Please try your request again.",
              createdAt: new Date(),
            },
          ])
        }
      } finally {
        abortRef.current = null
        setIsGenerating(false)
      }
    },
    [handleStreamEvent, hitlRequest]
  )

  return {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    append,
    stop,
    isGenerating,
    activeAgent,
    activeIntent,
    hitlRequest,
    respondToHitl,
    suggestions: SUPPORT_SUGGESTIONS,
  }
}
