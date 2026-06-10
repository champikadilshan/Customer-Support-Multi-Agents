"use client"

import { Toaster } from "sonner"

import { cn } from "@/lib/utils"
import { Chat } from "@/components/ui/chat"
import { useSupportChat } from "@/hooks/use-support-chat"

export function SupportChat() {
  const {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    stop,
    isLoading,
    isHitlPending,
    activeAgent,
    respondToHitl,
  } = useSupportChat()

  return (
    <>
      <div className={cn("flex h-[448px] w-full flex-col")}>
        <Chat
          className="h-full min-h-0"
          messages={messages}
          input={input}
          handleInputChange={handleInputChange}
          handleSubmit={handleSubmit}
          isGenerating={isLoading}
          isHitlPending={isHitlPending}
          activeAgent={activeAgent}
          respondToHitl={respondToHitl}
          stop={stop}
        />
      </div>

      <Toaster richColors position="top-center" />
    </>
  )
}
