export type AnswerProvider = 'LOCAL' | 'DEEPSEEK'
export type KnowledgeScope = 'INTERNAL' | 'INTERNAL_LIMITED' | 'GENERAL' | 'NONE'
export type AnswerStage = string

export interface AnswerMetrics {
  query_processing_ms?: number | null
  keyword_search_ms?: number | null
  vector_search_ms?: number | null
  rerank_ms?: number | null
  retrieval_ms?: number | null
  llm_first_token_ms?: number | null
  llm_generation_ms?: number | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_ms?: number | null
  source_count?: number | null
  provider?: string | null
  cache_hit?: boolean
  retrieval_query?: string | null
  retrieval_queries?: string[] | null
  query_rewrite_ms?: number | null
  question_type?: string | null
  question_type_label?: string | null
  confidence?: ConfidencePayload | null
  citation_check?: CitationCheckPayload | null
  no_answer?: NoAnswerPayload | null
  suggestions?: string[] | null
  node_timings?: Record<string, number> | null
}

export interface QueryRewriteInfo {
  original: string
  standalone_question: string
  retrieval_query: string
  queries: string[]
  used_context: boolean
  rewritten: boolean
  warning: string | null
}

export type ConfidenceTier = 'HIGH' | 'MEDIUM' | 'INSUFFICIENT'

export interface ConfidencePayload {
  tier: ConfidenceTier
  label: string
  reasons: string[]
  score: number
  factors: Record<string, number>
}

export interface CitationCheckPayload {
  checked: number
  supported: number
  invalid_numbers: number[]
  unsupported_sentences: string[]
  unavailable_citations: number[]
  ok: boolean
}

export interface NoAnswerDocument { id: string; name: string }

export interface NoAnswerPayload {
  reason: 'NO_RELEVANT_DOCUMENT' | 'PERMISSION_RESTRICTED' | 'LOW_RELEVANCE' | 'MODEL_UNAVAILABLE'
  message: string
  recommended_documents: NoAnswerDocument[]
  rephrase_suggestions: string[]
  allow_deepseek: boolean
  deepseek_configured: boolean
  missing_knowledge_reason: string
}

export interface AnswerSource {
  citation_number: number
  chunk_id: string
  document_id: string
  document_name: string
  extension: string
  document_version?: number | null
  sequence_number: number
  content: string
  page_start: number | null
  page_end: number | null
  slide_number: number | null
  sheet_name: string | null
  row_start: number | null
  row_end: number | null
  section_path: string[]
  ocr_confidence: number | null
  match_type: string
  score?: number | null
  retrieval_rank?: number | null
  pre_rerank_rank?: number | null
  post_rerank_rank?: number | null
}

export interface AnswerWarning { code: string; message: string }

export interface AnswerStatus {
  ollama: { reachable: boolean; model: string; installed: boolean }
  deepseek_configured: boolean
  deepseek_model: string
}

export type AnswerJobStatus =
  | 'PENDING' | 'RETRIEVING' | 'GENERATING' | 'VERIFYING'
  | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export interface AnswerJob {
  id: string
  conversation_id: string | null
  message_id: string | null
  status: AnswerJobStatus
  current_stage: string | null
  partial_content: string
  event_cursor: number
  metrics: Record<string, unknown>
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  cancelled_at: string | null
}

export interface AnswerEvent {
  type: 'stage' | 'sources' | 'delta' | 'replace' | 'warning' | 'metrics' | 'done' | 'error' | 'query_rewrite' | 'confidence' | 'citation_check' | 'no_answer' | 'suggestions' | 'harness_started' | 'tool_requested' | 'tool_running' | 'tool_result' | 'approval_required' | 'approval_result' | 'harness_done'
  stage?: AnswerStage | null
  provider?: AnswerProvider | null
  text?: string | null
  sources?: AnswerSource[] | null
  warning?: AnswerWarning | null
  metrics?: AnswerMetrics | null
  query_rewrite?: QueryRewriteInfo | null
  confidence?: ConfidencePayload | null
  citation_check?: CitationCheckPayload | null
  no_answer?: NoAnswerPayload | null
  detail?: Record<string, unknown> | null
  suggestions?: string[] | null
  question_type?: string | null
  scope?: KnowledgeScope | null
  deepseek_requested?: boolean | null
  deepseek_used?: boolean | null
  source_count?: number | null
  error?: { code: string; message: string } | null
  task_id?: string | null
  step?: number | null
  tool?: string | null
  tool_arguments?: Record<string, unknown> | null
  tool_result?: Record<string, unknown> | null
  approval?: HarnessApproval | null
}

export interface HarnessApproval {
  id: string; tool_name: string; context: string; namespace: string; target: string
  arguments: Record<string, unknown>; yaml_content?: string | null; dry_run_output?: string | null
  diff_output?: string | null; expires_at: string
}

export interface HarnessStep {
  number: number; tool: string; status: 'requested' | 'running' | 'succeeded' | 'failed' | 'awaiting'
  reason?: string; result?: Record<string, unknown>
}

export interface AnswerMessage {
  id: string
  question: string
  answer: string
  sources: AnswerSource[]
  warnings: AnswerWarning[]
  provider: AnswerProvider
  scope: KnowledgeScope | null
  stage: AnswerStage | null
  complete: boolean
  harnessTaskId: string | null
  harnessSteps: HarnessStep[]
  approval: HarnessApproval | null
}

export interface CitationSource {
  citation_number: number
  document_id: string
  chunk_id: string
  document_name: string
  content: string | null
  location_text: string
  score?: number | null
  available: boolean
  can_download?: boolean
  extension?: string | null
  version_number?: number | null
  matched_keywords?: string[]
  retrieval_rank?: number | null
  pre_rerank_rank?: number | null
  post_rerank_rank?: number | null
  cited_version?: number | null
  status: 'ACTIVE' | 'DISABLED' | 'DELETED' | 'FORBIDDEN' | 'VERSION_CHANGED'
  message?: string | null
  meta?: Record<string, unknown>
}

export interface AnswerTurn {
  key: string
  userMessageId: string | null
  assistantMessageId: string | null
  question: string
  answer: string
  sources: CitationSource[]
  warnings: AnswerWarning[]
  provider: string
  scope: KnowledgeScope | null
  metrics?: AnswerMetrics | null
  confidence?: ConfidencePayload | null
  citationCheck?: CitationCheckPayload | null
  noAnswer?: NoAnswerPayload | null
  questionType?: string | null
  suggestions?: string[]
  stageDetail?: Record<string, unknown> | null
  generating: boolean
  stage: string | null
  failed: boolean
  stopped: boolean
  jobId?: string | null
  cursor?: number
  errorMessage?: string
  harnessTaskId: string | null
  harnessSteps: HarnessStep[]
  approval: HarnessApproval | null
  sourcesVisible?: boolean
  feedbackRating?: 'UP' | 'DOWN' | null
  feedbackMode?: boolean
  feedbackReasons?: string[]
  feedbackComment?: string
  feedbackSubmitting?: boolean
  feedbackNotice?: { kind: 'success' | 'error'; message: string } | null
  pdfExporting?: boolean
  pdfExportNotice?: { kind: 'success' | 'error'; message: string } | null
}
