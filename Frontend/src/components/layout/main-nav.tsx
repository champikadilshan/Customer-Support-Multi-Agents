"use client"

import FitbitIcon from "@mui/icons-material/Fitbit"
import { usePathname } from "next/navigation"

import { cn } from "@/lib/utils"

const NAV_ITEMS = ["Demo", "Billing", "Sales", "Complaints"] as const

function AppLogo() {
  return (
    <div className="flex items-center gap-2">
      <FitbitIcon sx={{ fontSize: 28, color: "hsl(var(--foreground))" }} />
      <p className="hidden text-sm font-semibold tracking-tight sm:block">
        Customer Support
      </p>
    </div>
  )
}

export function MainNav() {
  const pathname = usePathname()

  return (
    <div className="mr-4 flex md:flex">
      <div className="mr-4 flex items-center lg:mr-6">
        <AppLogo />
      </div>
      <nav className="hidden items-center gap-4 text-sm md:flex lg:gap-6">
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
