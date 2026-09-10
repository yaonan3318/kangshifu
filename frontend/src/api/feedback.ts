import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { FeedbackListResponse } from '../types/feedback'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

export interface SubmitFeedbackInput {
  messageId: string
  rating: 'UP' | 'DOWN'
  reasons?: string[]
  comment?: string
}

export async function submitFeedback(body: SubmitFeedbackInput): Promise<{ ok: boolean }> {
  return parse(await fetch('/api/feedback', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message_id: body.messageId, rating: body.rating,
      reasons: body.reasons ?? [], comment: body.comment ?? null,
    }),
  }))
}

export interface FeedbackQuery {
  rating?: string
  resolved?: boolean
  assistant_id?: string
  username?: string
  created_from?: string
  created_to?: string
  no_answer?: boolean
  document_id?: string
  reason?: string
  page?: number
  page_size?: number
}

export const listFeedback = async (query: FeedbackQuery = {}): Promise<FeedbackListResponse> => {
  const params = new URLSearchParams({ page: String(query.page ?? 1), page_size: String(query.page_size ?? 30) })
  if (query.rating) params.set('rating', query.rating)
  if (query.resolved !== undefined) params.set('resolved', query.resolved ? 'true' : 'false')
  if (query.assistant_id) params.set('assistant_id', query.assistant_id)
  if (query.username) params.set('username', query.username)
  if (query.created_from) params.set('created_from', query.created_from)
  if (query.created_to) params.set('created_to', query.created_to)
  if (query.no_answer !== undefined) params.set('no_answer', String(query.no_answer))
  if (query.document_id) params.set('document_id', query.document_id)
  if (query.reason) params.set('reason', query.reason)
  return parse(await fetch(`/api/feedback?${params}`))
}

export const listFeedbackReasons = async (): Promise<{ items: string[] }> => parse(await fetch('/api/feedback/reasons'))

export const resolveFeedback = async (id: string, note: string): Promise<{ ok: boolean }> =>
  parse(await fetch(`/api/feedback/${id}/resolve`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note: note || null }),
  }))
