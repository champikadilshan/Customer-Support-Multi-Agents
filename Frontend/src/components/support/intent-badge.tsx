type IntentBadgeProps = {
  intent: string | null
  agent: string | null
}

const AGENT_LABELS: Record<string, string> = {
  billing: "Billing Agent",
  complaint: "Complaint Agent",
  sales: "Sales Agent",
}

export function IntentBadge({ intent, agent }: IntentBadgeProps) {
  if (!intent && !agent) return null

  const label = agent ? AGENT_LABELS[agent] ?? agent : intent

  return (
    <div className="rounded-full border bg-muted px-3 py-1 text-xs text-muted-foreground">
      Routed to <span className="font-medium text-foreground">{label}</span>
      {intent ? ` · ${intent}` : null}
    </div>
  )
}
