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
}

export interface AnswerSource {
  citation_number: number
  chunk_id: string
  document_id: string
  document_name: string
  extension: string
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
}

export interface AnswerWarning { code: string; message: string }

export interface AnswerStatus {
  ollama: { reachable: boolean; model: string; installed: boolean }
  deepseek_configured: boolean
  deepseek_model: string
}

export interface AnswerEvent {
  type: 'stage' | 'sources' | 'delta' | 'replace' | 'warning' | 'metrics' | 'done' | 'error' | 'harness_started' | 'tool_requested' | 'tool_running' | 'tool_result' | 'approval_required' | 'approval_result' | 'harness_done'
  stage?: AnswerStage | null
  provider?: AnswerProvider | null
  text?: string | null
  sources?: AnswerSource[] | null
  warning?: AnswerWarning | null
  metrics?: AnswerMetrics | null
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
  content: string
  location_text: string
  score?: number | null
  available: boolean
  status: 'ACTIVE' | 'DISABLED' | 'DELETED'
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
  generating: boolean
  stage: string | null
  failed: boolean
  stopped: boolean
  errorMessage?: string
  harnessTaskId: string | null
  harnessSteps: HarnessStep[]
  approval: HarnessApproval | null
  sourcesVisible?: boolean
}
