export interface AuditLogRecord {
  id: string
  user_id: string | null
  username: string | null
  action: string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown>
  ip_address: string | null
  success: boolean
  error_code: string | null
  request_id: string | null
  created_at: string
}

export interface AuditLogListResponse {
  items: AuditLogRecord[]
  page: number
  page_size: number
  total: number
}
