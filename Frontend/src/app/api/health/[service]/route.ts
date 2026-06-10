export const dynamic = "force-dynamic"

const SERVICE_PORTS: Record<string, number> = {
  orchestrator: 8001,
  billing: 8002,
  complaint: 8003,
  sales: 8004,
  ticket: 8000,
  mcp: 8005,
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ service: string }> }
) {
  const { service } = await params
  const port = SERVICE_PORTS[service]

  if (!port) {
    return Response.json({ error: "Unknown service" }, { status: 404 })
  }

  const backendHost = process.env.BACKEND_HOST ?? "localhost"

  try {
    const response = await fetch(`http://${backendHost}:${port}/health`, {
      cache: "no-store",
    })

    if (!response.ok) {
      return Response.json({ status: "down" }, { status: 200 })
    }

    return Response.json(await response.json())
  } catch {
    return Response.json({ status: "down" }, { status: 200 })
  }
}
