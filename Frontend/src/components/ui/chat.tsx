"use client"

import { forwardRef, useCallback, useEffect } from "react"
import { ArrowDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { useAutoScroll } from "@/hooks/use-auto-scroll"
import { getAgentStatusMessage } from "@/lib/agent-status"
import { Button } from "@/components/ui/button"
import { type Message } from "@/components/ui/chat-message"
import { CopyButton } from "@/components/ui/copy-button"
import { MessageInput } from "@/components/ui/message-input"
import { MessageList } from "@/components/ui/message-list"
import { ChatEmptyState } from "@/components/ui/chat-empty-state"

interface ChatProps {
  handleSubmit: (event?: { preventDefault?: () => void }) => void
  messages: Message[]
  input: string
  className?: string
  handleInputChange: React.ChangeEventHandler<HTMLTextAreaElement>
  isGenerating: boolean
  isHitlPending?: boolean
  activeAgent?: string | null
  activeIntent?: string | null
  respondToHitl?: (messageId: string, response: "yes" | "no") => void
  stop?: () => void
}

export function Chat({
  messages,
  handleSubmit,
  input,
  handleInputChange,
  stop,
  isGenerating,
  isHitlPending = false,
  activeAgent = null,
  activeIntent = null,
  respondToHitl,
  className,
}: ChatProps) {
  const lastMessage = messages.at(-1)
  const isEmpty = messages.length === 0

  const messageOptions = useCallback(
    (message: Message) => {
      const isLastAssistant =
        message.id === lastMessage?.id && message.role === "assistant"
      const hasActiveToolCall = message.toolInvocations?.some(
        (invocation) => invocation.state === "call"
      )

      return {
        actions: (
          <CopyButton
            content={message.content}
            copyMessage="Copied response to clipboard!"
          />
        ),
        isStreaming: isGenerating && isLastAssistant,
        enableTypewriter: Boolean(isLastAssistant && message.createdAt),
        statusMessage: getAgentStatusMessage({
          activeAgent,
          activeIntent,
          hasActiveToolCall: Boolean(hasActiveToolCall),
        }),
        isHitlResponding:
          isGenerating && Boolean(message.hitlResponse && message.hitlRequest),
        animation:
          message.hitlRequest || (isLastAssistant && isGenerating)
            ? ("none" as const)
            : ("scale" as const),
        onHitlRespond:
          message.hitlRequest && !message.hitlResponse && respondToHitl
            ? (response: "yes" | "no") => respondToHitl(message.id, response)
            : undefined,
      }
    },
    [activeAgent, activeIntent, isGenerating, lastMessage?.id, respondToHitl]
  )

  return (
    <ChatContainer className={className}>
      {isEmpty ? <ChatEmptyState /> : null}

      {messages.length > 0 ? (
        <ChatMessages
          isGenerating={isGenerating}
          isHitlPending={isHitlPending}
          messages={messages}
        >
          <MessageList
            messages={messages}
            showTimeStamps={false}
            messageOptions={messageOptions}
          />
        </ChatMessages>
      ) : null}

      <form
        className="shrink-0"
        onSubmit={(event) => {
          event.preventDefault()
          handleSubmit(event)
        }}
      >
        <MessageInput
          value={input}
          onChange={handleInputChange}
          stop={stop}
          isGenerating={isGenerating || isHitlPending}
        />
      </form>
    </ChatContainer>
  )
}

export function ChatMessages({
  messages,
  children,
  isGenerating = false,
  isHitlPending = false,
}: React.PropsWithChildren<{
  messages: Message[]
  isGenerating?: boolean
  isHitlPending?: boolean
}>) {
  const {
    containerRef,
    contentRef,
    scrollToBottom,
    handleScroll,
    shouldAutoScroll,
    handleTouchStart,
  } = useAutoScroll([messages, isGenerating, isHitlPending])

  useEffect(() => {
    if (!shouldAutoScroll) return

    scrollToBottom()

    const intervalId = window.setInterval(scrollToBottom, 48)
    return () => window.clearInterval(intervalId)
  }, [messages, isGenerating, isHitlPending, shouldAutoScroll, scrollToBottom])

  return (
    <div className="relative min-h-0 flex-1">
      <div
        className="scrollbar-hidden h-full overflow-y-auto overflow-x-hidden pb-4"
        ref={containerRef}
        onScroll={handleScroll}
        onTouchStart={handleTouchStart}
      >
        <div ref={contentRef} className="min-h-0">
          {children}
        </div>
      </div>

      {!shouldAutoScroll ? (
        <Button
          onClick={scrollToBottom}
          className="absolute bottom-2 right-0 z-10 h-8 w-8 rounded-full shadow-sm ease-in-out animate-in fade-in-0 slide-in-from-bottom-1"
          size="icon"
          variant="secondary"
          aria-label="Scroll to latest message"
        >
          <ArrowDown className="h-4 w-4" />
        </Button>
      ) : null}
    </div>
  )
}

export const ChatContainer = forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      className={cn("flex h-full min-h-0 w-full flex-col gap-3", className)}
      {...props}
    />
  )
})
ChatContainer.displayName = "ChatContainer"
