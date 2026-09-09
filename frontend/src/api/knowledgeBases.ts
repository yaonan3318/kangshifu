import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { KnowledgeBaseList, KnowledgeBaseRecord } from '../types/knowledgeBases'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = await response.json().catch(() => ({})) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

export const listKnowledgeBases = async (): Promise<KnowledgeBaseList> => parse(await fetch('/api/knowledge-bases'))
export const createKnowledgeBase = async (name: string, description: string): Promise<KnowledgeBaseRecord> => parse(await fetch('/api/knowledge-bases', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, description: description || null}) }))
export const updateKnowledgeBase = async (id: string, body: {name?:string;description?:string|null}): Promise<KnowledgeBaseRecord> => parse(await fetch(`/api/knowledge-bases/${id}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) }))
export const setKnowledgeBaseEnabled = async (id: string, enabled: boolean): Promise<KnowledgeBaseRecord> => parse(await fetch(`/api/knowledge-bases/${id}/${enabled?'enable':'disable'}`, {method:'POST'}))
