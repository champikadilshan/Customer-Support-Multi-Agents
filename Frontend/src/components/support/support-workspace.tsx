"use client"

import { Toaster } from "sonner"

import { cn } from "@/lib/utils"
import { Chat } from "@/components/ui/chat"
import { RightSidebar } from "@/components/support/right-sidebar"
import { useSupportChat } from "@/hooks/use-support-chat"

type SupportWorkspaceProps = {
  header: React.ReactNode
}

export function SupportWorkspace({ header }: SupportWorkspaceProps) {
  const chat = useSupportChat()

  return (
    <>
      <div className="container grid grid-cols-1 gap-8 md:grid-cols-2">
        <div className="flex flex-col">
          {header}

          <section className="px-4 pb-0">
            <div className={cn("flex h-[448px] w-full flex-col")}>
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
          </section>
        </div>

        <aside
          aria-label="Support sidebar"
          className="mt-12 hidden h-[calc(100vh-10rem)] min-h-[448px] px-4 md:block"
        >
          <RightSidebar
            graph={chat.agentGraph}
            isGraphLive={chat.isGraphLive}
          />
        </aside>
      </div>

      <Toaster richColors position="top-center" />
    </>
  )
}
