import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type {
  KnowledgeGap, KnowledgeGapListResponse, KnowledgeGapRerun, KnowledgeGapStats,
} from '../types/knowledgeGap'

async function parse<T>(response: Promise<Response> | Response): Promise<T> {
  const resolved = await response
  if (resolved.ok) return resolved.status === 204 ? (undefined as T) : resolved.json()
  const body = (await resolved.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const listKnowledgeGaps = (params: URLSearchParams): Promise<KnowledgeGapListResponse> =>
  parse<KnowledgeGapListResponse>(fetch(`/api/knowledge-gaps?${params}`))

export const getKnowledgeGapStats = (): Promise<KnowledgeGapStats> =>
  parse<KnowledgeGapStats>(fetch('/api/knowledge-gaps/statistics'))

export const updateKnowledgeGap = (
  id: string,
  body: { status?: string; assignee_user_id?: string | null; linked_document_ids?: string[]; note?: string | null },
): Promise<KnowledgeGap> =>
  parse<KnowledgeGap>(fetch(`/api/knowledge-gaps/${id}`, json('PATCH', body)))

export const rerunKnowledgeGap = (id: string): Promise<KnowledgeGapRerun> =>
  parse<KnowledgeGapRerun>(fetch(`/api/knowledge-gaps/${id}/rerun`, { method: 'POST' }))
