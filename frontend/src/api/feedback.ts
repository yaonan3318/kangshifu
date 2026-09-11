import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type {
  AnswerFeedbackRecord, FeedbackCaseDetail, FeedbackCaseListResponse, FeedbackListResponse,
  FeedbackStatistics, FeedbackType,
} from '../types/feedback'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

export interface SubmitFeedbackInput {
  messageId: string
  rating: FeedbackType
  feedbackType?: FeedbackType
  reasons?: string[]
  comment?: string
}

export async function submitFeedback(body: SubmitFeedbackInput): Promise<{ ok: boolean; id: string }> {
  return parse(await fetch('/api/feedback', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message_id: body.messageId, rating: body.rating,
      feedback_type: body.feedbackType ?? body.rating,
      reasons: body.reasons ?? [], comment: body.comment ?? null,
    }),
  }))
}

export const listFeedbackReasons = async (): Promise<{ items: string[] }> =>
  parse(await fetch('/api/feedback/reasons'))

export const listMyFeedback = async (page = 1, pageSize = 30): Promise<FeedbackListResponse> =>
  parse(await fetch(`/api/feedback/mine?page=${page}&page_size=${pageSize}`))

// ---------------------------------------------------------------- 管理端

export interface FeedbackCaseQuery {
  status?: string[]
  feedback_type?: string
  knowledge_base_id?: string
  assistant_id?: string
  assignee_id?: string
  keyword?: string
  created_from?: string
  created_to?: string
  page?: number
  page_size?: number
}

export const listFeedbackCases = async (query: FeedbackCaseQuery = {}): Promise<FeedbackCaseListResponse> => {
  const params = new URLSearchParams({ page: String(query.page ?? 1), page_size: String(query.page_size ?? 30) })
  for (const status of query.status ?? []) params.append('status', status)
  if (query.feedback_type) params.set('feedback_type', query.feedback_type)
  if (query.knowledge_base_id) params.set('knowledge_base_id', query.knowledge_base_id)
  if (query.assistant_id) params.set('assistant_id', query.assistant_id)
  if (query.assignee_id) params.set('assignee_id', query.assignee_id)
  if (query.keyword) params.set('keyword', query.keyword)
  if (query.created_from) params.set('created_from', query.created_from)
  if (query.created_to) params.set('created_to', query.created_to)
  return parse(await fetch(`/api/admin/feedback/cases?${params}`))
}

export const getFeedbackCase = async (id: string): Promise<FeedbackCaseDetail> =>
  parse(await fetch(`/api/admin/feedback/cases/${id}`))

export interface FeedbackCaseUpdateInput {
  status?: string
  priority?: string
  admin_note?: string | null
  conclusion?: string | null
  fix_document_id?: string | null
  fix_config_version_id?: string | null
  note?: string | null
}

export const updateFeedbackCase = async (id: string, body: FeedbackCaseUpdateInput): Promise<FeedbackCaseDetail> =>
  parse(await fetch(`/api/admin/feedback/cases/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))

export const assignFeedbackCase = async (
  id: string, body: { assignee_id?: string | null; priority?: string; note?: string | null },
): Promise<FeedbackCaseDetail> =>
  parse(await fetch(`/api/admin/feedback/cases/${id}/assign`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))

export const verifyFeedbackCase = async (id: string, conclusion?: string): Promise<FeedbackCaseDetail> =>
  parse(await fetch(`/api/admin/feedback/cases/${id}/verify`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conclusion: conclusion ?? null }),
  }))

export const feedbackStatistics = async (query: {
  knowledge_base_id?: string; assistant_id?: string; config_version_id?: string
} = {}): Promise<FeedbackStatistics> => {
  const params = new URLSearchParams()
  if (query.knowledge_base_id) params.set('knowledge_base_id', query.knowledge_base_id)
  if (query.assistant_id) params.set('assistant_id', query.assistant_id)
  if (query.config_version_id) params.set('config_version_id', query.config_version_id)
  return parse(await fetch(`/api/admin/feedback/statistics?${params}`))
}

export const feedbackConfigComparison = async (left: string, right: string): Promise<{
  left: Record<string, number | null>
  right: Record<string, number | null>
  differences: Array<{ key: string; left: number | null; right: number | null; delta: number | null }>
}> => parse(await fetch(`/api/admin/feedback/config-comparison?left=${left}&right=${right}`))

export type { AnswerFeedbackRecord, FeedbackType }
