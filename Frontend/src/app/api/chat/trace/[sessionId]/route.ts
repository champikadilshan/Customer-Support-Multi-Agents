export const dynamic = "force-dynamic"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8001"

  const response = await fetch(`${backendUrl}/chat/trace/${sessionId}`, {
    headers: {
      Accept: "text/event-stream",
      Connection: "keep-alive",
      "Cache-Control": "no-cache",
    },
    cache: "no-store",
  })

  if (!response.ok) {
    return Response.json(
      { error: "Failed to connect to trace stream" },
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
