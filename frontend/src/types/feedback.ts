export type FeedbackType = 'UP' | 'DOWN' | 'REPORT'
export type FeedbackCaseStatus = 'PENDING' | 'PROCESSING' | 'WAIT_VERIFY' | 'RESOLVED' | 'IGNORED'
export type FeedbackPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT'
export type VerificationStatus = 'NOT_RUN' | 'RUNNING' | 'PASSED' | 'FAILED' | 'ERROR'

export interface FeedbackSourceRef {
  document_id: string
  document_name: string
  chunk_id?: string
  citation_number: number | null
  score?: number | null
}

export interface AnswerFeedbackRecord {
  id: string
  message_id: string
  session_id: string | null
  user_id: string | null
  username: string | null
  rating: FeedbackType
  feedback_type: FeedbackType
  reasons: string[]
  comment: string | null
  question: string | null
  answer_content: string
  sources: FeedbackSourceRef[]
  assistant_id: string | null
  assistant_name: string | null
  knowledge_scope: string | null
  knowledge_base_ids: string[]
  retrieval_config_version_id: string | null
  provider: string | null
  answer_model: string | null
  no_answer: boolean
  case_id: string | null
  case_status: FeedbackCaseStatus | null
  created_at: string
  updated_at: string | null
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

export interface FeedbackCaseSummary {
  id: string
  feedback_id: string
  status: FeedbackCaseStatus
  priority: FeedbackPriority
  assignee_id: string | null
  created_at: string
  updated_at: string
  resolved_at: string | null
  first_handled_at: string | null
  last_verification_result: VerificationStatus | null
  question: string | null
  feedback_type: FeedbackType
  rating: FeedbackType
  reasons: string[]
  comment: string | null
  user_id: string | null
  username: string | null
  assistant_id: string | null
  knowledge_base_ids: string[]
  answer_preview: string
}

export interface FeedbackCaseEvent {
  id: string
  event_type: string
  from_status: string | null
  to_status: string | null
  actor_id: string | null
  note: string | null
  detail: Record<string, unknown>
  created_at: string
}

export interface VerificationRun {
  id: string
  status: VerificationStatus
  question: string | null
  before_answer: string | null
  before_sources: Record<string, unknown>[]
  before_config_version_id: string | null
  after_answer: string | null
  after_sources: Record<string, unknown>[]
  after_config_version_id: string | null
  after_message_id: string | null
  base_score: number | null
  final_score: number | null
  no_answer: boolean | null
  duration_ms: number | null
  admin_conclusion: string | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}

export interface FeedbackCaseDetail extends FeedbackCaseSummary {
  admin_note: string | null
  conclusion: string | null
  fix_document_id: string | null
  fix_config_version_id: string | null
  assignee_name: string | null
  message_id: string
  session_id: string | null
  session_title: string | null
  assistant_name: string | null
  answer_snapshot: string | null
  knowledge_scope: string | null
  retrieval_config_version_id: string | null
  answer_model: string | null
  answer_provider: string | null
  documents: Array<{
    document_id: string
    document_name: string
    chunk_id: string
    citation_number: number | null
    score: number | null
    content_snapshot: string
    feedback_version: number | null
    current_version: number | null
    deleted: boolean
    enabled: boolean
    status: string | null
  }>
  events: FeedbackCaseEvent[]
  verifications: VerificationRun[]
}

export interface FeedbackCaseListResponse {
  items: FeedbackCaseSummary[]
  page: number
  page_size: number
  total: number
  status_options: FeedbackCaseStatus[]
}

export interface FeedbackStatistics {
  overall: Record<string, number | null>
  knowledge_bases: Array<Record<string, unknown>>
  assistants: Array<Record<string, unknown>>
  config_versions: Array<Record<string, unknown>>
  aggregates: Array<Record<string, unknown>>
  enabled: boolean
  parameters: Record<string, number | boolean>
}
