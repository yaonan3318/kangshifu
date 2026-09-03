export type AnswerProvider = 'LOCAL' | 'DEEPSEEK'
export type KnowledgeScope = 'INTERNAL' | 'INTERNAL_LIMITED' | 'GENERAL' | 'NONE'
export type AnswerStage = 'retrieving' | 'local_generating' | 'deepseek_enhancing'

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
}

export interface AnswerWarning { code: string; message: string }

export interface AnswerStatus {
  ollama: { reachable: boolean; model: string; installed: boolean }
  deepseek_configured: boolean
  deepseek_model: string
}

export interface AnswerEvent {
  type: 'stage' | 'sources' | 'delta' | 'replace' | 'warning' | 'done' | 'error'
  stage?: AnswerStage | null
  provider?: AnswerProvider | null
  text?: string | null
  sources?: AnswerSource[] | null
  warning?: AnswerWarning | null
  scope?: KnowledgeScope | null
  deepseek_requested?: boolean | null
  deepseek_used?: boolean | null
  source_count?: number | null
  error?: { code: string; message: string } | null
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
}
