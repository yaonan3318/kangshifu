import { ApiError } from './documents'
import type { ApiErrorBody, DocumentChunk } from '../types/documents'

export interface ChunkList { items: DocumentChunk[]; page:number; page_size:number; total:number }
async function parse<T>(response:Promise<Response>|Response):Promise<T>{ const resolved=await response; if(resolved.ok)return resolved.json(); const body=await resolved.json().catch(()=>({})) as ApiErrorBody; throw new ApiError(body.error?.code||'REQUEST_FAILED',body.error?.message||'请求失败',body.error?.details) }
export const listChunks=(documentId:string,page=1,pageSize=25):Promise<ChunkList>=>parse(fetch(`/api/documents/${documentId}/chunks?page=${page}&page_size=${pageSize}`))
export const updateChunk=(id:string,content:string):Promise<DocumentChunk>=>parse(fetch(`/api/chunks/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({content})}))
export const setChunkEnabled=(id:string,enabled:boolean):Promise<DocumentChunk>=>parse(fetch(`/api/chunks/${id}/${enabled?'enable':'disable'}`,{method:'POST'}))
export const reindexChunk=(id:string):Promise<DocumentChunk>=>parse(fetch(`/api/chunks/${id}/reindex`,{method:'POST'}))
export const restoreChunk=(id:string):Promise<DocumentChunk>=>parse(fetch(`/api/chunks/${id}/restore-original`,{method:'POST'}))
