export type HitlRequest = {
  request_id: string
  question: string
  ticket_preview: {
    title?: string
    category?: string
    priority?: string
  }
  options: string[]
}
