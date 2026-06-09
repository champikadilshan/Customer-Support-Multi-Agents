import type { Metadata } from "next"
import { GeistSans } from "geist/font/sans"

import { ThemeProvider } from "@/components/providers"
import { cn } from "@/lib/utils"

import "./globals.css"

export const metadata: Metadata = {
  title: "virtusa-multi-agent",
  description:
    "Customer support powered by AI billing, sales, and complaint agents in one place.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={cn(
          "min-h-screen bg-background font-sans antialiased",
          GeistSans.variable
        )}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          <div className="relative flex min-h-screen flex-col bg-background">
            {children}
          </div>
        </ThemeProvider>
      </body>
    </html>
  )
}
