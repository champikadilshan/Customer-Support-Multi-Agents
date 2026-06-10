export const dynamic = "force-dynamic"

export async function POST(request: Request) {
  const body = await request.json()
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8001"

  const response = await fetch(`${backendUrl}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    return Response.json(
      { error: detail?.detail ?? "Failed to reach support backend" },
      { status: response.status }
    )
  }

  return Response.json(await response.json())
}
