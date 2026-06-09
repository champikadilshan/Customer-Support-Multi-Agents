"use client"

import { useEffect, useState } from "react"

type UseTypewriterOptions = {
  speed?: number
  charsPerTick?: number
  onUpdate?: () => void
}

export function useTypewriter(
  text: string,
  { speed = 8, charsPerTick = 2, onUpdate }: UseTypewriterOptions = {}
) {
  const [displayedLength, setDisplayedLength] = useState(0)

  useEffect(() => {
    if (displayedLength > text.length) {
      setDisplayedLength(text.length)
    }
  }, [text, displayedLength])

  useEffect(() => {
    if (displayedLength >= text.length) {
      return
    }

    const timeout = window.setTimeout(() => {
      setDisplayedLength((current) =>
        Math.min(current + charsPerTick, text.length)
      )
      onUpdate?.()
    }, speed)

    return () => window.clearTimeout(timeout)
  }, [text, displayedLength, speed, charsPerTick, onUpdate])

  return {
    displayedText: text.slice(0, displayedLength),
    isComplete: displayedLength >= text.length,
  }
}
