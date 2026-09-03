export type DocumentStatus = 'PENDING' | 'DELETING'

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

