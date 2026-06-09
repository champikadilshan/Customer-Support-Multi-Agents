export type SseEvent =
  | { type: "session"; data: { session_id: string } }
  | { type: "intent"; data: { intent: string; agent: string; request_id: string } }
  | { type: "tool_call"; data: { tool: string } }
  | { type: "token"; data: { text: string } }
  | { type: "done"; data: { request_id: string; agent: string; status: string } }
  | { type: "error"; data: { message: string } }
  | {
      type: "hitl_request"
      data: {
        request_id: string
        question: string
        ticket_preview: {
          title?: string
          category?: string
          priority?: string
        }
        options: string[]
      }
    }

export async function* parseSseStream(
  body: ReadableStream<Uint8Array> | null
): AsyncGenerator<SseEvent> {
  if (!body) return

  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split("\n\n")
    buffer = frames.pop() ?? ""

    for (const frame of frames) {
      const event = parseSseFrame(frame)
      if (event) yield event
    }
  }

  if (buffer.trim()) {
    const event = parseSseFrame(buffer)
    if (event) yield event
  }
}

function parseSseFrame(frame: string): SseEvent | null {
  const lines = frame.split("\n")
  let eventType = "message"
  let data = ""

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith("data:")) {
      data += line.slice(5).trim()
    }
  }

  if (!data) return null

  try {
    const parsed = JSON.parse(data)
    return { type: eventType as SseEvent["type"], data: parsed } as SseEvent
  } catch {
    return null
  }
}

export async function consumeSseStream(
  url: string,
  body: unknown,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal
) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }

  for await (const event of parseSseStream(response.body)) {
    onEvent(event)
  }
}
