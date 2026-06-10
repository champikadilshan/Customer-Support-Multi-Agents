export const dynamic = "force-dynamic"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8001"

  const response = await fetch(
    `${backendUrl}/chat/trace/${encodeURIComponent(sessionId)}/replay`,
    { cache: "no-store" }
  )

  if (!response.ok) {
    return Response.json(
      { error: "Failed to fetch trace replay" },
      { status: response.status }
    )
  }

  return Response.json(await response.json())
}
