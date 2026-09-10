import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { AuditLogListResponse } from '../types/audit'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.status === 204 ? (undefined as T) : response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'REQUEST_FAILED', body.error?.message ?? '请求失败', body.error?.details, response.status)
}

export interface AuditQuery {
  action?: string
  target_type?: string
  username?: string
  success?: boolean
  created_from?: string
  created_to?: string
  page?: number
  page_size?: number
}

export async function listAuditLogs(query: AuditQuery = {}): Promise<AuditLogListResponse> {
  const params = new URLSearchParams()
  if (query.action) params.set('action', query.action)
  if (query.target_type) params.set('target_type', query.target_type)
  if (query.username) params.set('username', query.username)
  if (query.success !== undefined) params.set('success', String(query.success))
  if (query.created_from) params.set('created_from', query.created_from)
  if (query.created_to) params.set('created_to', query.created_to)
  params.set('page', String(query.page ?? 1))
  params.set('page_size', String(query.page_size ?? 50))
  return parse(await fetch(`/api/audit/logs?${params}`))
}
