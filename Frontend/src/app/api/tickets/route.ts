export async function GET() {
  const ticketServiceUrl =
    process.env.TICKET_SERVICE_URL ?? "http://localhost:8000"

  const response = await fetch(`${ticketServiceUrl}/tickets`, {
    cache: "no-store",
  })

  if (!response.ok) {
    return Response.json(
      { error: "Failed to fetch tickets" },
      { status: response.status }
    )
  }

  return Response.json(await response.json())
}
