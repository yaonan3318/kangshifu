export interface AnswerFeedbackRecord {
  id: string
  message_id: string
  session_title: string | null
  user_id: string | null
  username: string | null
  rating: 'UP' | 'DOWN'
  reasons: string[]
  comment: string | null
  answer_content: string
  created_at: string
  resolved_at: string | null
  resolved_by: string | null
  resolution_note: string | null
}

export interface FeedbackListResponse {
  items: AnswerFeedbackRecord[]
  page: number
  page_size: number
  total: number
}
