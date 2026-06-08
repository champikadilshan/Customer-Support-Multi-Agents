"use client"

import { forwardRef, useCallback } from "react"
import { ArrowDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { useAutoScroll } from "@/hooks/use-auto-scroll"
import { Button } from "@/components/ui/button"
import { type Message } from "@/components/ui/chat-message"
import { CopyButton } from "@/components/ui/copy-button"
import { MessageInput } from "@/components/ui/message-input"
import { MessageList } from "@/components/ui/message-list"
import { PromptSuggestions } from "@/components/ui/prompt-suggestions"

interface ChatPropsBase {
  handleSubmit: (event?: { preventDefault?: () => void }) => void
  messages: Message[]
  input: string
  className?: string
  handleInputChange: React.ChangeEventHandler<HTMLTextAreaElement>
  isGenerating: boolean
  stop?: () => void
}

interface ChatPropsWithoutSuggestions extends ChatPropsBase {
  append?: never
  suggestions?: never
}

interface ChatPropsWithSuggestions extends ChatPropsBase {
  append: (message: { role: "user"; content: string }) => void
  suggestions: string[]
}

type ChatProps = ChatPropsWithoutSuggestions | ChatPropsWithSuggestions

export function Chat({
  messages,
  handleSubmit,
  input,
  handleInputChange,
  stop,
  isGenerating,
  append,
  suggestions,
  className,
}: ChatProps) {
  const lastMessage = messages.at(-1)
  const isEmpty = messages.length === 0
  const isTyping = lastMessage?.role === "user"

  const messageOptions = useCallback(
    (message: Message) => ({
      actions: (
        <CopyButton
          content={message.content}
          copyMessage="Copied response to clipboard!"
        />
      ),
    }),
    []
  )

  return (
    <ChatContainer className={className}>
      {isEmpty && append && suggestions ? (
        <PromptSuggestions
          label="How can we help you today?"
          append={append}
          suggestions={suggestions}
        />
      ) : null}

      {messages.length > 0 ? (
        <ChatMessages messages={messages}>
          <MessageList
            messages={messages}
            isTyping={isTyping}
            showTimeStamps={false}
            messageOptions={messageOptions}
          />
        </ChatMessages>
      ) : null}

      <form
        className="mt-52"
        onSubmit={(event) => {
          event.preventDefault()
          handleSubmit(event)
        }}
      >
        <MessageInput
          value={input}
          onChange={handleInputChange}
          stop={stop}
          isGenerating={isGenerating}
        />
      </form>
    </ChatContainer>
  )
}

export function ChatMessages({
  messages,
  children,
}: React.PropsWithChildren<{
  messages: Message[]
}>) {
  const {
    containerRef,
    scrollToBottom,
    handleScroll,
    shouldAutoScroll,
    handleTouchStart,
  } = useAutoScroll([messages])

  return (
    <div
      className="grid max-h-[320px] grid-cols-1 overflow-y-auto pb-4"
      ref={containerRef}
      onScroll={handleScroll}
      onTouchStart={handleTouchStart}
    >
      <div className="max-w-full [grid-column:1/1] [grid-row:1/1]">
        {children}
      </div>

      {!shouldAutoScroll && (
        <div className="pointer-events-none flex flex-1 items-end justify-end [grid-column:1/1] [grid-row:1/1]">
          <div className="sticky bottom-0 left-0 flex w-full justify-end">
            <Button
              onClick={scrollToBottom}
              className="pointer-events-auto h-8 w-8 rounded-full ease-in-out animate-in fade-in-0 slide-in-from-bottom-1"
              size="icon"
              variant="ghost"
            >
              <ArrowDown className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
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
      className={cn("flex w-full flex-col", className)}
      {...props}
    />
  )
})
ChatContainer.displayName = "ChatContainer"
