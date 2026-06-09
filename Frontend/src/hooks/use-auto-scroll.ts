import { useCallback, useEffect, useRef, useState } from "react"

const ACTIVATION_THRESHOLD = 50
const MIN_SCROLL_UP_THRESHOLD = 10

export function useAutoScroll(dependencies: React.DependencyList) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const previousScrollTop = useRef<number | null>(null)
  const [shouldAutoScroll, setShouldAutoScroll] = useState(true)

  const scrollToBottom = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    container.scrollTop = container.scrollHeight
  }, [])

  const scrollToBottomSoon = useCallback(() => {
    scrollToBottom()
    requestAnimationFrame(() => {
      scrollToBottom()
      requestAnimationFrame(scrollToBottom)
    })
  }, [scrollToBottom])

  const handleScroll = () => {
    if (!containerRef.current) return

    const { scrollTop, scrollHeight, clientHeight } = containerRef.current
    const distanceFromBottom = Math.abs(
      scrollHeight - scrollTop - clientHeight
    )
    const isScrollingUp = previousScrollTop.current
      ? scrollTop < previousScrollTop.current
      : false
    const scrollUpDistance = previousScrollTop.current
      ? previousScrollTop.current - scrollTop
      : 0
    const isDeliberateScrollUp =
      isScrollingUp && scrollUpDistance > MIN_SCROLL_UP_THRESHOLD

    if (isDeliberateScrollUp) {
      setShouldAutoScroll(false)
    } else {
      setShouldAutoScroll(distanceFromBottom < ACTIVATION_THRESHOLD)
    }

    previousScrollTop.current = scrollTop
  }

  const handleTouchStart = () => {
    setShouldAutoScroll(false)
  }

  useEffect(() => {
    if (containerRef.current) {
      previousScrollTop.current = containerRef.current.scrollTop
    }
  }, [])

  useEffect(() => {
    if (shouldAutoScroll) {
      scrollToBottomSoon()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies)

  useEffect(() => {
    const container = containerRef.current
    const content = contentRef.current
    if (!container || !content || !shouldAutoScroll) return

    const observer = new ResizeObserver(() => {
      scrollToBottomSoon()
    })

    observer.observe(content)
    observer.observe(container)

    return () => observer.disconnect()
  }, [shouldAutoScroll, scrollToBottomSoon])

  return {
    containerRef,
    contentRef,
    scrollToBottom: scrollToBottomSoon,
    handleScroll,
    shouldAutoScroll,
    handleTouchStart,
  }
}
