"use client"

import { useCallback, useEffect, useState } from "react"

import { fetchTickets, type Ticket } from "@/lib/tickets"

const REFRESH_INTERVAL_MS = 10_000

export function useTickets() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadTickets = useCallback(async () => {
    try {
      setError(null)
      const data = await fetchTickets()
      setTickets(data)
    } catch {
      setError("Unable to load tickets right now.")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadTickets()

    const interval = window.setInterval(() => {
      void loadTickets()
    }, REFRESH_INTERVAL_MS)

    const handleRefresh = () => {
      void loadTickets()
    }

    window.addEventListener("tickets:refresh", handleRefresh)

    return () => {
      window.clearInterval(interval)
      window.removeEventListener("tickets:refresh", handleRefresh)
    }
  }, [loadTickets])

  return {
    tickets,
    isLoading,
    error,
    refresh: loadTickets,
  }
}

export function refreshTicketsPanel() {
  window.dispatchEvent(new Event("tickets:refresh"))
}
