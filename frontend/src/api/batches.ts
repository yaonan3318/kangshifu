import { ApiError } from './documents'
import type { ApiErrorBody, UploadProgress } from '../types/documents'
import type { BatchCreate, BatchDetail, BatchFileRecord, BatchList, BatchRecord } from '../types/batches'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = await response.json().catch(() => ({})) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}
export async function createBatch(body: BatchCreate): Promise<BatchRecord> { return parse(await fetch('/api/batches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})) }
export async function listBatches(): Promise<BatchList> { return parse(await fetch('/api/batches')) }
export async function getBatch(id:string): Promise<BatchDetail> { return parse(await fetch(`/api/batches/${id}`)) }
export async function cancelBatch(id:string): Promise<BatchRecord> { return parse(await fetch(`/api/batches/${id}/cancel`,{method:'POST'})) }
export async function retryBatchFile(batch:string,id:string): Promise<BatchFileRecord> { return parse(await fetch(`/api/batches/${batch}/files/${id}/retry`,{method:'POST'})) }
export async function ignoreBatchFile(batch:string,id:string): Promise<BatchFileRecord> { return parse(await fetch(`/api/batches/${batch}/files/${id}/ignore`,{method:'POST'})) }
export function uploadBatchFile(batch:string,file:File,path:string,onProgress:(value:UploadProgress)=>void):Promise<BatchFileRecord>{
  return new Promise((resolve,reject)=>{ const request=new XMLHttpRequest(); request.open('POST',`/api/batches/${batch}/files`)
    request.upload.onprogress=e=>onProgress({loaded:e.loaded,total:e.lengthComputable?e.total:file.size})
    request.onload=()=>{ try { const body=JSON.parse(request.responseText||'{}') as BatchFileRecord & ApiErrorBody; request.status<300?resolve(body):reject(new ApiError(body.error?.code||'UPLOAD_FAILED',body.error?.message||'上传失败',body.error?.details)) } catch { reject(new ApiError('INVALID_RESPONSE','本地服务返回了无法识别的响应')) } }
    request.onerror=()=>reject(new ApiError('NETWORK_ERROR','无法连接本地服务')); const form=new FormData(); form.append('relative_path',path); form.append('file',file); request.send(form)
  })
}
