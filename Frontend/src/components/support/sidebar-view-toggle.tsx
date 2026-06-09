"use client"

import { GitBranch, Ticket } from "lucide-react"

import { cn } from "@/lib/utils"

export type SidebarView = "tickets" | "graph"

type SidebarViewToggleProps = {
  value: SidebarView
  onChange: (view: SidebarView) => void
}

export function SidebarViewToggle({ value, onChange }: SidebarViewToggleProps) {
  return (
    <div
      className="inline-flex shrink-0 rounded-full border bg-muted/40 p-0.5"
      role="group"
      aria-label="Sidebar view"
    >
      <button
        type="button"
        aria-label="Tickets"
        aria-pressed={value === "tickets"}
        onClick={() => onChange("tickets")}
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
          value === "tickets"
            ? "bg-foreground text-background shadow-sm"
            : "text-muted-foreground hover:text-foreground"
        )}
      >
        <Ticket className="h-3 w-3" />
        Tickets
      </button>
      <button
        type="button"
        aria-label="Agent Flow"
        aria-pressed={value === "graph"}
        onClick={() => onChange("graph")}
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
          value === "graph"
            ? "bg-foreground text-background shadow-sm"
            : "text-muted-foreground hover:text-foreground"
        )}
      >
        <GitBranch className="h-3 w-3" />
        Flow
      </button>
    </div>
  )
}
