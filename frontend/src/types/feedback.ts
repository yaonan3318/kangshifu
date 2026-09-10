export interface FeedbackSourceRef {
  document_id: string
  document_name: string
  citation_number: number
}

export interface AnswerFeedbackRecord {
  id: string
  message_id: string
  session_id: string | null
  session_title: string | null
  user_id: string | null
  username: string | null
  rating: 'UP' | 'DOWN'
  reasons: string[]
  comment: string | null
  question: string | null
  answer_content: string
  sources: FeedbackSourceRef[]
  assistant_id: string | null
  assistant_name: string | null
  provider: string | null
  knowledge_scope: string | null
  metrics: Record<string, number | null>
  no_answer: boolean
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
