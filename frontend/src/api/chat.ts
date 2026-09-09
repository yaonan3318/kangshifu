import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { ChatSessionDetail, ChatSessionItem, ChatSessionListResponse } from '../types/chat'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.status === 204 ? (undefined as T) : response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

function sessionParams(search?: string, archived?: boolean, page = 1, pageSize = 50): URLSearchParams {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (search) params.set('search', search)
  if (archived !== undefined) params.set('archived', archived ? 'true' : 'false')
  return params
}

export const listChatSessions = async (search?: string, archived?: boolean): Promise<ChatSessionListResponse> =>
  parse(await fetch(`/api/chat/sessions?${sessionParams(search, archived)}`))

export const createChatSession = async (title?: string): Promise<ChatSessionDetail> =>
  parse(await fetch('/api/chat/sessions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title || null }),
  }))

export const getChatSession = async (id: string): Promise<ChatSessionDetail> =>
  parse(await fetch(`/api/chat/sessions/${id}`))

export const renameChatSession = async (id: string, title: string): Promise<ChatSessionDetail> =>
  parse(await fetch(`/api/chat/sessions/${id}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  }))

export const archiveChatSession = async (id: string): Promise<ChatSessionItem> =>
  parse(await fetch(`/api/chat/sessions/${id}/archive`, { method: 'POST' }))

export const restoreChatSession = async (id: string): Promise<ChatSessionItem> =>
  parse(await fetch(`/api/chat/sessions/${id}/restore`, { method: 'POST' }))

export const deleteChatSession = async (id: string, purge = false): Promise<void> =>
  parse(await fetch(`/api/chat/sessions/${id}?purge=${purge}`, { method: 'DELETE' }))
