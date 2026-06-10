export const dynamic = "force-dynamic"

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8001"

  const response = await fetch(
    `${backendUrl}/session/${encodeURIComponent(sessionId)}`,
    { cache: "no-store" }
  )

  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    return Response.json(
      { error: detail?.detail ?? "Session not found" },
      { status: response.status }
    )
  }

  return Response.json(await response.json())
}
