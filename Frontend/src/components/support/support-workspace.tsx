"use client"

import { Toaster } from "sonner"

import { cn } from "@/lib/utils"
import { Chat } from "@/components/ui/chat"
import { RightSidebar } from "@/components/support/right-sidebar"
import { useSupportChat } from "@/hooks/use-support-chat"

export function SupportWorkspace() {
  const chat = useSupportChat()

  return (
    <>
      <div className="container grid grid-cols-1 gap-8 pt-[42px] md:grid-cols-[7fr_3fr]">
        <aside
          aria-label="Support sidebar"
          className="order-2 hidden h-[calc(100vh-7rem-42px)] min-h-[448px] px-4 md:order-1 md:block"
        >
          <RightSidebar
            graph={chat.agentGraph}
            isGraphLive={chat.isGraphLive}
          />
        </aside>

        <div
          className={cn(
            "order-1 flex h-[calc(100vh-7rem-42px)] min-h-[448px] w-full flex-col overflow-hidden rounded-lg border border-border px-4 pb-2.5 pt-4 md:order-2"
          )}
        >
          <Chat
            className="h-full min-h-0"
            messages={chat.messages}
            input={chat.input}
            handleInputChange={chat.handleInputChange}
            handleSubmit={chat.handleSubmit}
            append={chat.append}
            suggestions={chat.suggestions}
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
