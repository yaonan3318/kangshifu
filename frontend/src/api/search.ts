import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { SearchResponse } from '../types/search'

export interface SearchFilters {
  extension: string
  documentName: string
  createdFrom: string
  createdTo: string
  knowledgeBaseId?: string
  tags?: string[]
  departmentId?: string
  ownerUserId?: string
  documentStatus?: string
  relativePath?: string
  versionNumber?: string
  validOnly?: boolean
}

export async function searchDocuments(query: string, filters: SearchFilters): Promise<SearchResponse> {
  const response = await fetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query, extension: filters.extension || null, document_name: filters.documentName.trim() || null,
      created_from: filters.createdFrom || null, created_to: filters.createdTo || null, limit: 10,
      knowledge_base_id: filters.knowledgeBaseId || null, tags: filters.tags || [],
      department_id: filters.departmentId || null, owner_user_id: filters.ownerUserId || null,
      document_status: filters.documentStatus || null, relative_path: filters.relativePath || null,
      version_number: filters.versionNumber ? Number(filters.versionNumber) : null,
      valid_only: filters.validOnly ?? false,
    }),
  })
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'SEARCH_FAILED', body.error?.message ?? '检索失败', body.error?.details)
}
