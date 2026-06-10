export const SESSION_STORAGE_KEY = "support_session_id"
const LEGACY_SESSION_STORAGE_KEY = "support-chat-session-id"

export function readStoredSessionId(): string | null {
  if (typeof window === "undefined") return null

  const current = localStorage.getItem(SESSION_STORAGE_KEY)
  if (current) return current

  const legacy = localStorage.getItem(LEGACY_SESSION_STORAGE_KEY)
  if (legacy) {
    localStorage.setItem(SESSION_STORAGE_KEY, legacy)
    localStorage.removeItem(LEGACY_SESSION_STORAGE_KEY)
    return legacy
  }

  return null
}

export function persistSessionId(sessionId: string) {
  localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
}

export function clearStoredSessionId() {
  localStorage.removeItem(SESSION_STORAGE_KEY)
  localStorage.removeItem(LEGACY_SESSION_STORAGE_KEY)
}
