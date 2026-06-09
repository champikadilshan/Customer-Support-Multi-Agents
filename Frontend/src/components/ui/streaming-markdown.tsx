"use client"

import { useCallback } from "react"

import { useTypewriter } from "@/hooks/use-typewriter"
import { MarkdownRenderer } from "@/components/ui/markdown-renderer"

interface StreamingMarkdownProps {
  content: string
  isStreaming: boolean
  onUpdate?: () => void
}

export function StreamingMarkdown({
  content,
  isStreaming,
  onUpdate,
}: StreamingMarkdownProps) {
  const handleUpdate = useCallback(() => {
    onUpdate?.()
  }, [onUpdate])

  const { displayedText, isComplete } = useTypewriter(content, {
    speed: 10,
    charsPerTick: 3,
    onUpdate: handleUpdate,
  })

  if (isComplete && !isStreaming) {
    return <MarkdownRenderer>{content}</MarkdownRenderer>
  }

  const showCursor = isStreaming || !isComplete

  return (
    <span className="inline">
      <MarkdownRenderer>{displayedText}</MarkdownRenderer>
      {showCursor ? (
        <span
          aria-hidden
          className="ml-0.5 inline-block h-4 w-0.5 translate-y-px animate-pulse bg-foreground align-middle"
        />
      ) : null}
    </span>
  )
}
