"use client"

import React, { useRef } from "react"
import { ArrowUp, Mic, Paperclip, Square } from "lucide-react"

import { cn } from "@/lib/utils"
import { useAutosizeTextArea } from "@/hooks/use-autosize-textarea"
import { Button } from "@/components/ui/button"

interface MessageInputProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  value: string
  submitOnEnter?: boolean
  stop?: () => void
  isGenerating: boolean
}

export function MessageInput({
  placeholder = "Ask about billing, sales, or complaints...",
  className,
  onKeyDown: onKeyDownProp,
  submitOnEnter = true,
  stop,
  isGenerating,
  ...props
}: MessageInputProps) {
  const textAreaRef = useRef<HTMLTextAreaElement>(null)

  useAutosizeTextArea({
    ref: textAreaRef,
    maxHeight: 240,
    borderWidth: 1,
    dependencies: [props.value],
  })

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (submitOnEnter && event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      if (!isGenerating && props.value.trim()) {
        event.currentTarget.form?.requestSubmit()
      }
    }

    onKeyDownProp?.(event)
  }

  return (
    <div className="relative flex w-full">
      <div className="relative flex-1">
        <textarea
          aria-label="Write your prompt here"
          placeholder={placeholder}
          ref={textAreaRef}
          onKeyDown={onKeyDown}
          className={cn(
            "z-10 w-full grow resize-none rounded-xl border border-input bg-background p-3 pr-32 text-sm ring-offset-background transition-[border] placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
            className
          )}
          {...props}
        />
      </div>

      <div className="absolute right-3 top-3 z-20 flex gap-2">
        <Button
          type="button"
          size="icon"
          variant="outline"
          className="h-8 w-8"
          aria-label="Attach a file"
        >
          <Paperclip className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          className="h-8 w-8"
          aria-label="Voice input"
          size="icon"
        >
          <Mic className="h-4 w-4" />
        </Button>
        {isGenerating && stop ? (
          <Button
            type="button"
            size="icon"
            className="h-8 w-8"
            aria-label="Stop generating"
            onClick={stop}
          >
            <Square className="h-3 w-3 animate-pulse" fill="currentColor" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            className="h-8 w-8 transition-opacity"
            aria-label="Send message"
            disabled={!props.value.trim() || isGenerating}
          >
            <ArrowUp className="h-5 w-5" />
          </Button>
        )}
      </div>
    </div>
  )
}
