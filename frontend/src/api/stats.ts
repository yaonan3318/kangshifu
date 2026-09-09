import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

export interface StatsOverview {
  days: number
  questions: number
  questions_today: number
  active_users: number
  answers: number
  avg_first_token_ms: number | null
  avg_answer_ms: number | null
  avg_retrieval_ms: number | null
  cache_hits: number
  provider_counts: Record<string, number>
  local_success_rate: number | null
  deepseek_success_rate: number | null
  no_answer_count: number
  no_answer_samples: Array<{ message_id: string; question: string; created_at: string }>
  feedback: { total: number; up: number; down: number }
  top_queries: Array<{ question: string; count: number }>
  top_documents: Array<{ document_id: string; document_name: string; count: number }>
  failures: { parse_failed: number; index_failed: number }
  backlog: number
}

export const getStatsOverview = async (days = 7): Promise<StatsOverview> =>
  parse(await fetch(`/api/stats/overview?days=${days}`))

export const getAnswerTrace = async (messageId: string): Promise<Record<string, unknown>> =>
  parse(await fetch(`/api/stats/trace/${messageId}`))
