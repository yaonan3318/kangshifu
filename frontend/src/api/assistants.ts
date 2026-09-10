import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { AssistantListResponse, AssistantRecord, AssistantWelcome } from '../types/assistant'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

export const listAssistants = async (enabled?: boolean): Promise<AssistantListResponse> => {
  const query = enabled === undefined ? '' : `?enabled=${enabled}`
  return parse(await fetch(`/api/assistants${query}`))
}

export const getAssistant = async (id: string): Promise<AssistantRecord> =>
  parse(await fetch(`/api/assistants/${id}`))

export const getAssistantWelcome = async (id: string): Promise<AssistantWelcome> =>
  parse(await fetch(`/api/assistants/${id}/welcome`))

export interface AssistantUpsertInput {
  name?: string
  description?: string | null
  avatar?: string
  welcome_message?: string | null
  system_prompt?: string | null
  model_provider?: string
  model_name?: string | null
  use_deepseek_allowed?: boolean
  default_deepseek_enabled?: boolean
  deepseek_enabled?: boolean
  harness_enabled?: boolean
  harness_context?: string | null
  harness_namespace?: string
  retrieval_limit?: number
  temperature?: number
  recommended_questions?: string[]
  answer_template?: string
  internet_enabled?: boolean
  no_answer_policy?: string
  capabilities?: string[]
  limitations?: string[]
  chatflow_id?: string | null
  enabled?: boolean
}

export const createAssistant = async (body: AssistantUpsertInput): Promise<AssistantRecord> =>
  parse(await fetch('/api/assistants', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))

export const updateAssistant = async (id: string, body: AssistantUpsertInput): Promise<AssistantRecord> =>
  parse(await fetch(`/api/assistants/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))

export const setAssistantEnabled = async (id: string, enabled: boolean): Promise<AssistantRecord> =>
  parse(await fetch(`/api/assistants/${id}/${enabled ? 'enable' : 'disable'}`, { method: 'POST' }))

export const setAssistantKnowledgeBases = async (id: string, knowledgeBaseIds: string[]): Promise<AssistantRecord> =>
  parse(await fetch(`/api/assistants/${id}/knowledge-bases`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ knowledge_base_ids: knowledgeBaseIds }),
  }))

export const deleteAssistant = async (id: string): Promise<void> => {
  await parse(await fetch(`/api/assistants/${id}`, { method: 'DELETE' }))
}
