"use client"

import { usePathname } from "next/navigation"

import { cn } from "@/lib/utils"

const NAV_ITEMS = ["Demo", "Billing", "Sales", "Complaints"] as const

export function MainNav() {
  const pathname = usePathname()

  return (
    <div className="mr-4 hidden md:flex">
      <div className="mr-4 flex items-center space-x-2 lg:mr-6">
        <span className="hidden font-bold lg:inline-block">
          virtusa-multi-agent
        </span>
      </div>
      <nav className="flex items-center gap-4 text-sm lg:gap-6">
        {NAV_ITEMS.map((item) => {
          const isActive = item === "Demo" && pathname === "/"

          return (
            <span
              key={item}
              className={cn(
                "cursor-default transition-colors hover:text-foreground/80",
                isActive ? "text-foreground" : "text-foreground/60"
              )}
            >
              {item}
            </span>
          )
        })}
      </nav>
    </div>
  )
}
