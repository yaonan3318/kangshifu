import type { ApiErrorBody, DocumentContent, DocumentList, DocumentRecord, UploadProgress } from '../types/documents'

export class ApiError extends Error {
  constructor(public code: string, message: string, public details?: Record<string, unknown>) {
    super(message)
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.status === 204 ? (undefined as T) : response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'REQUEST_FAILED', body.error?.message ?? '请求失败', body.error?.details)
}

export function uploadDocument(file: File, onProgress: (progress: UploadProgress) => void): Promise<DocumentRecord> {
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
    request.send(form)
  })
}

export async function listDocuments(params: URLSearchParams): Promise<DocumentList> {
  return parseResponse(await fetch(`/api/documents?${params}`))
}

export async function deleteDocument(id: string): Promise<void> {
  await parseResponse<void>(await fetch(`/api/documents/${id}`, { method: 'DELETE' }))
}

export async function getDocumentContent(id: string, page = 1, pageSize = 25): Promise<DocumentContent> {
  return parseResponse(await fetch(`/api/documents/${id}/content?page=${page}&page_size=${pageSize}`))
}

export async function reprocessDocument(id: string): Promise<DocumentRecord> {
  return parseResponse(await fetch(`/api/documents/${id}/reprocess`, { method: 'POST' }))
}

export function downloadUrl(id: string): string {
  return `/api/documents/${id}/download`
}
