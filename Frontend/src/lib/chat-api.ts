import type { TicketPreview } from "@/lib/hitl"

export type ChatResponse = {
  session_id: string
  response: string
  hitl_pending?: boolean
  request_id?: string
  ticket_preview?: TicketPreview
  hitl_question?: string
  hitl_options?: string[]
}

export type SessionInfo = {
  session_id: string
  message_count: number
  active_agent: string | null
  metadata?: Record<string, unknown>
  created_at?: string
  last_active?: string
}

export class ChatApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ChatApiError"
    this.status = status
  }
}

export async function postChat(message: string,sessionId: string | null): Promise<ChatResponse> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  })

  if (!response.ok) {
    throw new ChatApiError("Chat request failed", response.status)
  }

  return response.json() as Promise<ChatResponse>
}

export async function getSession(sessionId: string): Promise<SessionInfo> {
  const response = await fetch(`/api/session/${encodeURIComponent(sessionId)}`, {
    cache: "no-store",
  })

  if (!response.ok) {
    throw new ChatApiError("Session not found", response.status)
  }

  return response.json() as Promise<SessionInfo>
}
