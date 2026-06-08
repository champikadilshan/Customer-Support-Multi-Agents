"use client"

import { Toaster } from "sonner"

import { cn } from "@/lib/utils"
import { Chat } from "@/components/ui/chat"
import { HitlDialog } from "@/components/support/hitl-dialog"
import { useSupportChat } from "@/hooks/use-support-chat"

export function SupportChat() {
  const {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    append,
    stop,
    isGenerating,
    hitlRequest,
    respondToHitl,
    suggestions,
  } = useSupportChat()

  return (
    <>
      <div className={cn("flex h-[500px] w-full flex-col")}>
        <Chat
          className="grow"
          messages={messages}
          input={input}
          handleInputChange={handleInputChange}
          handleSubmit={handleSubmit}
          append={append}
          suggestions={suggestions}
          isGenerating={isGenerating}
          stop={stop}
        />
      </div>

      {hitlRequest ? (
        <div className="mt-4">
          <HitlDialog
            request={hitlRequest}
            onRespond={respondToHitl}
            disabled={isGenerating}
          />
        </div>
      ) : null}

      <Toaster richColors position="top-center" />
    </>
  )
}
