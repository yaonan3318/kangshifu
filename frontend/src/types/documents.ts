export type DocumentStatus = 'PENDING' | 'PARSING' | 'CHUNKING' | 'PARSED' | 'PARSE_FAILED' | 'OCR_FAILED' | 'DELETING'

export interface DocumentRecord {
  id: string
  original_name: string
  extension: string
  mime_type: string
  size_bytes: number
  sha256: string
  status: DocumentStatus
  error_code: string | null
  error_message: string | null
  parser_name: string | null
  parser_version: string | null
  created_at: string
  updated_at: string
}

export interface DocumentList {
  items: DocumentRecord[]
  page: number
  page_size: number
  total: number
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string; details?: Record<string, unknown> }
}

export interface UploadProgress {
  loaded: number
  total: number
}

export interface DocumentChunk {
  id: string
  sequence_number: number
  page_start: number | null
  page_end: number | null
  slide_number: number | null
  sheet_name: string | null
  row_start: number | null
  row_end: number | null
  section_path: string[]
  content: string
  ocr_confidence: number | null
}

export interface DocumentContent {
  items: DocumentChunk[]
  page: number
  page_size: number
  total: number
}
