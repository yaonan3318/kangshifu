import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type {
  ChatflowDebugResult, ChatflowGraph, ChatflowRecord, ChatflowVersion, NodeTypeDef,
} from '../types/chatflow'

async function parse<T>(response: Promise<Response> | Response): Promise<T> {
  const resolved = await response
  if (resolved.ok) return resolved.status === 204 ? (undefined as T) : resolved.json()
  const body = (await resolved.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const listChatflows = async (): Promise<ChatflowRecord[]> =>
  (await parse<{ items: ChatflowRecord[] }>(fetch('/api/chatflows'))).items

export const listNodeTypes = async (): Promise<NodeTypeDef[]> =>
  (await parse<{ items: NodeTypeDef[] }>(fetch('/api/chatflows/node-types'))).items

export const createChatflow = (body: { name: string; description?: string | null; graph?: ChatflowGraph }): Promise<ChatflowRecord> =>
  parse<ChatflowRecord>(fetch('/api/chatflows', json('POST', body)))

export const updateChatflow = (id: string, body: { name?: string; description?: string | null; graph?: ChatflowGraph; enabled?: boolean }): Promise<ChatflowRecord> =>
  parse<ChatflowRecord>(fetch(`/api/chatflows/${id}`, json('PATCH', body)))

export const deleteChatflow = (id: string): Promise<void> =>
  parse<void>(fetch(`/api/chatflows/${id}`, { method: 'DELETE' }))

export const publishChatflow = (id: string, note: string | null): Promise<ChatflowVersion> =>
  parse<ChatflowVersion>(fetch(`/api/chatflows/${id}/publish`, json('POST', { note })))

export const rollbackChatflow = (id: string, version: number): Promise<ChatflowRecord> =>
  parse<ChatflowRecord>(fetch(`/api/chatflows/${id}/rollback`, json('POST', { version })))

export const listChatflowVersions = (id: string): Promise<ChatflowVersion[]> =>
  parse<ChatflowVersion[]>(fetch(`/api/chatflows/${id}/versions`))

export const debugChatflow = (id: string, body: { question: string; knowledge_base_id?: string | null; include_generation?: boolean }): Promise<ChatflowDebugResult> =>
  parse<ChatflowDebugResult>(fetch(`/api/chatflows/${id}/debug`, json('POST', body)))
