import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { SearchResponse } from '../types/search'

export interface SearchFilters { extension: string; documentName: string; createdFrom: string; createdTo: string }

export async function searchDocuments(query: string, filters: SearchFilters): Promise<SearchResponse> {
  const response = await fetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query, extension: filters.extension || null, document_name: filters.documentName.trim() || null,
      created_from: filters.createdFrom || null, created_to: filters.createdTo || null, limit: 10,
    }),
  })
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'SEARCH_FAILED', body.error?.message ?? '检索失败', body.error?.details)
}
