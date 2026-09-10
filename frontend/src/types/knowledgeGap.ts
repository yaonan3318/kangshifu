export type KnowledgeGapStatus = 'OPEN' | 'ASSIGNED' | 'RESOLVED' | 'IGNORED'

export interface KnowledgeGap {
  id: string
  question: string
  reason: string
  count: number
  status: KnowledgeGapStatus
  assignee_user_id: string | null
  linked_document_ids: string[]
  note: string | null
  sample_message_id: string | null
  sample_answer: string | null
  latest_answer: string | null
  latest_confidence: string | null
  rerun_at: string | null
  last_seen_at: string
  created_at: string
  updated_at: string
}

export interface KnowledgeGapListResponse {
  items: KnowledgeGap[]
  page: number
  page_size: number
  total: number
}

export interface KnowledgeGapStats {
  total: number
  open: number
  assigned: number
  resolved: number
  ignored: number
  by_status: Record<string, number>
  by_reason: Record<string, number>
}

export interface KnowledgeGapRerun {
  gap_id: string
  question: string
  before: string | null
  after: string | null
  confidence: Record<string, unknown> | null
  source_count: number
}
