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
      // FastMCP on :8005 has no /health — 404 means the process is up but unprobed
      if (service === "mcp" && response.status === 404) {
        return Response.json({ status: "unknown", service: "sales_mcp" })
      }
      return Response.json({ status: "down" }, { status: 200 })
    }

    return Response.json(await response.json())
  } catch {
    return Response.json({ status: "down" }, { status: 200 })
  }
}
