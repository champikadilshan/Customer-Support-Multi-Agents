"use client"

import { RotateCcw } from "lucide-react"
import { Toaster } from "sonner"

import { cn } from "@/lib/utils"
import { Chat } from "@/components/ui/chat"
import { RightSidebar } from "@/components/support/right-sidebar"
import { Button } from "@/components/ui/button"
import { useSupportChat } from "@/hooks/use-support-chat"

export function SupportWorkspace() {
  const chat = useSupportChat()

  return (
    <>
      <div className="flex w-full gap-6 pt-[42px] pl-3 pr-4 md:pl-5 md:pr-6">
        <aside
          aria-label="Support sidebar"
          className="order-2 hidden h-[calc(100vh-7rem-42px)] min-h-[448px] min-w-0 flex-1 md:order-1 md:block"
        >
          <RightSidebar
            graph={chat.agentGraph}
            isGraphLive={chat.isGraphLive}
          />
        </aside>

        <div
          className={cn(
            "order-1 flex h-[calc(100vh-7rem-42px)] min-h-[448px] w-full flex-col overflow-hidden rounded-lg border border-border px-4 pb-2.5 pt-4 md:order-2 md:w-[min(100%,360px)] md:shrink-0 lg:w-[380px]"
          )}
        >
          <div className="mb-2 flex shrink-0 justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1.5 text-muted-foreground"
              onClick={() => void chat.resetSession()}
              disabled={chat.isGenerating || chat.isHitlPending || chat.isResetting}
              aria-label="Reset chat session"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset
            </Button>
          </div>

          <Chat
            className="min-h-0 flex-1"
            messages={chat.messages}
            input={chat.input}
            handleInputChange={chat.handleInputChange}
            handleSubmit={chat.handleSubmit}
            isGenerating={chat.isGenerating}
            isHitlPending={chat.isHitlPending}
            activeAgent={chat.activeAgent}
            activeIntent={chat.activeIntent}
            respondToHitl={chat.respondToHitl}
            stop={chat.stop}
          />
        </div>
      </div>

      <Toaster richColors position="top-center" />
    </>
  )
}
