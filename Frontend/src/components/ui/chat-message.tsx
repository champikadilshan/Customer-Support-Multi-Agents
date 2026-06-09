"use client"

import React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Ban, Loader2, Terminal } from "lucide-react"

import { cn } from "@/lib/utils"
import { AgentActivityIndicator } from "@/components/ui/agent-activity-indicator"
import { MarkdownRenderer } from "@/components/ui/markdown-renderer"
import { StreamingMarkdown } from "@/components/ui/streaming-markdown"

const chatBubbleVariants = cva(
  "group/message relative break-words rounded-lg p-3 text-sm sm:max-w-[70%]",
  {
    variants: {
      isUser: {
        true: "bg-primary text-primary-foreground",
        false: "bg-muted text-foreground",
      },
      animation: {
        none: "",
        slide: "duration-300 animate-in fade-in-0",
        scale: "duration-300 animate-in fade-in-0 zoom-in-75",
        fade: "duration-500 animate-in fade-in-0",
      },
    },
    compoundVariants: [
      {
        isUser: true,
        animation: "slide",
        class: "slide-in-from-right",
      },
      {
        isUser: false,
        animation: "slide",
        class: "slide-in-from-left",
      },
      {
        isUser: true,
        animation: "scale",
        class: "origin-bottom-right",
      },
      {
        isUser: false,
        animation: "scale",
        class: "origin-bottom-left",
      },
    ],
  }
)

type Animation = VariantProps<typeof chatBubbleVariants>["animation"]

interface ToolCall {
  state: "call"
  toolName: string
}

interface ToolResult {
  state: "result"
  toolName: string
  result: {
    __cancelled?: boolean
    [key: string]: unknown
  }
}

type ToolInvocation = ToolCall | ToolResult

export interface Message {
  id: string
  role: "user" | "assistant" | (string & {})
  content: string
  createdAt?: Date
  toolInvocations?: ToolInvocation[]
}

export interface ChatMessageProps extends Message {
  showTimeStamp?: boolean
  animation?: Animation
  actions?: React.ReactNode
  isStreaming?: boolean
  enableTypewriter?: boolean
  statusMessage?: string
}

export const ChatMessage: React.FC<ChatMessageProps> = ({
  role,
  content,
  createdAt,
  showTimeStamp = false,
  animation = "scale",
  actions,
  toolInvocations,
  isStreaming = false,
  enableTypewriter = false,
  statusMessage = "Analyzing your request",
}) => {
  const isUser = role === "user"
  const hasActiveToolCall = toolInvocations?.some(
    (invocation) => invocation.state === "call"
  )

  const activeToolCalls =
    toolInvocations?.filter((invocation) => invocation.state === "call") ?? []

  const formattedTime = createdAt?.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  })

  const renderAssistantContent = () => {
    if (isStreaming && !content) {
      return (
        <AgentActivityIndicator
          message={
            hasActiveToolCall
              ? "Running tools in the background"
              : statusMessage
          }
        />
      )
    }

    if (enableTypewriter && content) {
      return (
        <StreamingMarkdown content={content} isStreaming={isStreaming} />
      )
    }

    if (content) {
      return <MarkdownRenderer>{content}</MarkdownRenderer>
    }

    return null
  }

  if (isUser) {
    return (
      <div className="flex flex-col items-end">
        <div className={cn(chatBubbleVariants({ isUser, animation }))}>
          <MarkdownRenderer>{content}</MarkdownRenderer>
        </div>

        {showTimeStamp && createdAt ? (
          <time
            dateTime={createdAt.toISOString()}
            className="mt-1 block px-1 text-xs opacity-50 duration-500 animate-in fade-in-0"
          >
            {formattedTime}
          </time>
        ) : null}
      </div>
    )
  }

  if (isStreaming && activeToolCalls.length > 0) {
    return (
      <div className="flex flex-col items-start gap-2">
        <ToolCall toolInvocations={activeToolCalls} />
        <div className={cn(chatBubbleVariants({ isUser, animation }))}>
          {renderAssistantContent()}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-start">
      <div className={cn(chatBubbleVariants({ isUser, animation }))}>
        {renderAssistantContent()}
        {actions && !isStreaming ? (
          <div className="absolute -bottom-4 right-2 flex space-x-1 rounded-lg border bg-background p-1 text-foreground opacity-0 transition-opacity group-hover/message:opacity-100">
            {actions}
          </div>
        ) : null}
      </div>

      {showTimeStamp && createdAt ? (
        <time
          dateTime={createdAt.toISOString()}
          className="mt-1 block px-1 text-xs opacity-50 duration-500 animate-in fade-in-0"
        >
          {formattedTime}
        </time>
      ) : null}
    </div>
  )
}

function ToolCall({
  toolInvocations,
}: Pick<ChatMessageProps, "toolInvocations">) {
  if (!toolInvocations?.length) return null

  return (
    <>
      {toolInvocations.map((invocation, index) => {
        const isCancelled =
          invocation.state === "result" &&
          invocation.result.__cancelled === true

        if (isCancelled) {
          return (
            <div
              key={index}
              className="flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm text-muted-foreground"
            >
              <Ban className="h-4 w-4" />
              <span>
                Cancelled{" "}
                <span className="font-mono">{invocation.toolName}</span>
              </span>
            </div>
          )
        }

        if (invocation.state === "call") {
          return (
            <div
              key={index}
              className="flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm text-muted-foreground"
            >
              <Terminal className="h-4 w-4" />
              <span>
                Calling{" "}
                <span className="font-mono">{invocation.toolName}</span>
                ...
              </span>
              <Loader2 className="h-3 w-3 animate-spin" />
            </div>
          )
        }

        return null
      })}
    </>
  )
}
