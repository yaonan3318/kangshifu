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

export const listFeedback = async (resolved?: boolean, page = 1): Promise<FeedbackListResponse> => {
  const params = new URLSearchParams({ page: String(page), page_size: '30' })
  if (resolved !== undefined) params.set('resolved', resolved ? 'true' : 'false')
  return parse(await fetch(`/api/feedback?${params}`))
}

export const resolveFeedback = async (id: string, note: string): Promise<{ ok: boolean }> =>
  parse(await fetch(`/api/feedback/${id}/resolve`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note: note || null }),
  }))
