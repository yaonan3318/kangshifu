export type ChatMessageRole = 'USER' | 'ASSISTANT' | 'SYSTEM'
export type ChatMessageStatus = 'GENERATING' | 'COMPLETED' | 'FAILED' | 'STOPPED'
export type ChatProvider = 'LOCAL' | 'DEEPSEEK' | 'HARNESS'

export interface SourceLocation {
  page_start?: number | null
  page_end?: number | null
  slide_number?: number | null
  sheet_name?: string | null
  row_start?: number | null
  row_end?: number | null
  sequence_number?: number | null
  section_path?: string[]
  extension?: string | null
  match_type?: string | null
  text?: string
  [key: string]: unknown
}

export interface ChatSourceSnapshot {
  id: string
  citation_number: number
  document_id: string
  chunk_id: string
  document_name: string
  content_snapshot: string
  location_snapshot: SourceLocation
  score?: number | null
  available: boolean
  status: 'ACTIVE' | 'DISABLED' | 'DELETED'
}

export interface ChatMessageRecord {
  id: string
  session_id: string
  role: ChatMessageRole
  content: string
  provider: ChatProvider | null
  knowledge_scope: string | null
  status: ChatMessageStatus
  error_code: string | null
  error_message: string | null
  created_at: string
  completed_at: string | null
  sources: ChatSourceSnapshot[]
}

export interface ChatSessionItem {
  id: string
  title: string
  assistant_id: string | null
  created_at: string
  updated_at: string
  last_message_at: string | null
  archived_at: string | null
  message_count: number
  last_preview: string | null
}

export interface ChatSessionDetail extends ChatSessionItem {
  messages: ChatMessageRecord[]
}

export interface ChatSessionListResponse {
  items: ChatSessionItem[]
  total: number
}
