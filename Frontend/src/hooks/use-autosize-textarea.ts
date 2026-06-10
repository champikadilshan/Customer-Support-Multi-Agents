import { useLayoutEffect } from "react"

interface UseAutosizeTextAreaProps {
  ref: React.RefObject<HTMLTextAreaElement | null>
  maxHeight?: number
  borderWidth?: number
  dependencies: React.DependencyList
}

export function useAutosizeTextArea({
  ref,
  maxHeight = Number.MAX_SAFE_INTEGER,
  borderWidth = 0,
  dependencies,
}: UseAutosizeTextAreaProps) {
  useLayoutEffect(() => {
    if (!ref.current) return

    const currentRef = ref.current
    const borderAdjustment = borderWidth * 2
    const minHeight = currentRef.scrollHeight - borderAdjustment

    currentRef.style.removeProperty("height")
    const scrollHeight = currentRef.scrollHeight
    const clampedToMax = Math.min(scrollHeight, maxHeight)
    const clampedToMin = Math.max(clampedToMax, minHeight)

    currentRef.style.height = `${clampedToMin + borderAdjustment}px`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [maxHeight, ref, ...dependencies])
}
