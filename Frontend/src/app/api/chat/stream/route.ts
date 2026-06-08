export async function POST(request: Request) {
  const body = await request.json()
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8001"

  const response = await fetch(`${backendUrl}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    return Response.json(
      { error: "Failed to reach support backend" },
      { status: response.status }
    )
  }

  return new Response(response.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  })
}
