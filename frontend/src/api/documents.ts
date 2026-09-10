import type { ApiErrorBody, DocumentContent, DocumentList, DocumentRecord, UploadProgress } from '../types/documents'

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
    public status?: number,
  ) {
    super(message)
  }
}

const STATUS_FALLBACK: Record<number, string> = {
  401: '登录已失效，请重新登录',
  403: '没有操作权限',
  404: '对象不存在或无权查看',
  409: '名称重复或状态冲突',
  422: '输入参数不正确',
  500: '系统内部错误',
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.status === 204 ? (undefined as T) : response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(
    body.error?.code ?? 'REQUEST_FAILED',
    body.error?.message ?? STATUS_FALLBACK[response.status] ?? '请求失败',
    body.error?.details,
    response.status,
  )
}

export function uploadDocument(file: File, onProgress: (progress: UploadProgress) => void, knowledgeBaseId?: string): Promise<DocumentRecord> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', '/api/documents/upload')
    request.upload.onprogress = (event) => onProgress({ loaded: event.loaded, total: event.lengthComputable ? event.total : file.size })
    request.onload = () => {
      try {
        const body = JSON.parse(request.responseText || '{}') as DocumentRecord & ApiErrorBody
        if (request.status >= 200 && request.status < 300) resolve(body)
        else reject(new ApiError(body.error?.code ?? 'UPLOAD_FAILED', body.error?.message ?? '上传失败', body.error?.details))
      } catch {
        reject(new ApiError('INVALID_RESPONSE', '本地服务返回了无法识别的响应'))
      }
    }
    request.onerror = () => reject(new ApiError('NETWORK_ERROR', '无法连接本地服务'))
    const form = new FormData()
    form.append('file', file)
    if (knowledgeBaseId) form.append('knowledge_base_id', knowledgeBaseId)
    request.send(form)
  })
}

export async function listDocuments(params: URLSearchParams): Promise<DocumentList> {
  return parseResponse(await fetch(`/api/documents?${params}`))
}

export async function deleteDocument(id: string): Promise<void> {
  await parseResponse<void>(await fetch(`/api/documents/${id}`, { method: 'DELETE' }))
}

export async function getDocument(id: string): Promise<DocumentRecord> {
  return parseResponse(await fetch(`/api/documents/${id}`))
}

export async function restoreDocument(id: string): Promise<DocumentRecord> { return parseResponse(await fetch(`/api/documents/${id}/restore`, {method:'POST'})) }
export async function purgeDocument(id: string): Promise<void> { await parseResponse<void>(await fetch(`/api/documents/${id}/purge`, {method:'DELETE'})) }
export async function setDocumentEnabled(id: string, enabled: boolean): Promise<DocumentRecord> { return parseResponse(await fetch(`/api/documents/${id}/${enabled?'enable':'disable'}`, {method:'POST'})) }
export interface DocumentUpdateInput {
  knowledge_base_id?: string
  relative_path?: string
  tags?: string[]
  metadata?: Record<string, unknown>
  author?: string | null
  department_id?: string | null
  topic?: string | null
  related_document_ids?: string[]
  valid_from?: string | null
  valid_until?: string | null
}
export async function updateDocument(id: string, body: DocumentUpdateInput): Promise<DocumentRecord> { return parseResponse(await fetch(`/api/documents/${id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})) }
export async function listDocumentVersions(id: string): Promise<DocumentRecord[]> { return parseResponse(await fetch(`/api/documents/${id}/versions`)) }

export async function getDocumentContent(id: string, page = 1, pageSize = 25): Promise<DocumentContent> {
  return parseResponse(await fetch(`/api/documents/${id}/content?page=${page}&page_size=${pageSize}`))
}

export async function reprocessDocument(id: string): Promise<DocumentRecord> {
  return parseResponse(await fetch(`/api/documents/${id}/reprocess`, { method: 'POST' }))
}

export function downloadUrl(id: string): string {
  return `/api/documents/${id}/download`
}

export interface AclEntry {
  subject_type: 'DEPARTMENT' | 'ROLE' | 'USER'
  subject_id: string
  permission: 'READ' | 'MANAGE'
}

export interface AclItem extends AclEntry {
  id: string
  subject_name: string | null
}

export async function getDocumentAcl(id: string): Promise<{ items: AclItem[] }> {
  return parseResponse(await fetch(`/api/documents/${id}/acl`))
}

export interface AclReferences {
  departments: Array<{ id: string; name: string; parent_id: string | null; enabled: boolean; children: AclReferences['departments'] }>
  roles: Array<{ id: string; name: string; enabled: boolean }>
  users: Array<{ id: string; display_name: string; username: string; enabled: boolean }>
}

export async function getAclReferences(): Promise<AclReferences> {
  return parseResponse(await fetch('/api/documents/acl-references'))
}

export async function setDocumentAccess(id: string, body: { visibility?: string; acl?: AclEntry[] }): Promise<DocumentRecord> {
  return parseResponse(await fetch(`/api/documents/${id}/access`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export async function setDocumentExternalPolicy(id: string, body: { sensitivity_level: string; external_llm_allowed: boolean }): Promise<DocumentRecord> {
  return parseResponse(await fetch(`/api/documents/${id}/external-policy`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export interface ChunkPreviewItem {
  sequence_number: number
  content: string
  length: number
  page_start: number | null
  page_end: number | null
  slide_number: number | null
  sheet_name: string | null
  row_start: number | null
  row_end: number | null
  section_path: string[]
  block_type: string
  chunk_role: string
}

export interface ChunkPreviewResponse {
  items: ChunkPreviewItem[]
  total: number
  config: Record<string, unknown>
}

export async function previewDocumentChunks(
  id: string,
  body: { chunking_config?: Record<string, unknown> | null; limit?: number } = {},
): Promise<ChunkPreviewResponse> {
  return parseResponse(await fetch(`/api/documents/${id}/chunk-preview`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}
