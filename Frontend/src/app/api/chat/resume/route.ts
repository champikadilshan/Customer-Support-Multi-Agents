export async function POST(request: Request) {
  const body = await request.json()
  const complaintUrl = process.env.COMPLAINT_AGENT_URL ?? "http://localhost:8003"

  const response = await fetch(`${complaintUrl}/process/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    return Response.json(
      { error: "Failed to resume complaint flow" },
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
