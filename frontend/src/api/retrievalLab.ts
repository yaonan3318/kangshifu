import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { RetrievalCase, RetrievalInspect, RetrievalRun } from '../types/retrievalLab'
async function parse<T>(response:Promise<Response>|Response):Promise<T>{const resolved=await response;if(resolved.ok)return resolved.status===204?undefined as T:resolved.json();const body=await resolved.json().catch(()=>({})) as ApiErrorBody;throw new ApiError(body.error?.code||'REQUEST_FAILED',body.error?.message||'请求失败',body.error?.details)}
export const inspectRetrieval=(query:string,knowledgeBaseId?:string):Promise<RetrievalInspect>=>parse(fetch('/api/retrieval-lab/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,knowledge_base_id:knowledgeBaseId||null,limit:10})}))
export const listRetrievalCases=async():Promise<RetrievalCase[]>=>(await parse<{items:RetrievalCase[]}>(fetch('/api/retrieval-lab/cases'))).items
export const createRetrievalCase=(body:{name:string;question:string;knowledge_base_id:string|null;expected_document_ids:string[];expected_keywords:string[];expected_no_answer:boolean}):Promise<RetrievalCase>=>parse(fetch('/api/retrieval-lab/cases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}))
export const deleteRetrievalCase=(id:string):Promise<void>=>parse(fetch(`/api/retrieval-lab/cases/${id}`,{method:'DELETE'}))
export const runRetrievalCases=():Promise<RetrievalRun>=>parse(fetch('/api/retrieval-lab/runs',{method:'POST'}))
export const listRetrievalRuns=async():Promise<RetrievalRun[]>=>(await parse<{items:RetrievalRun[]}>(fetch('/api/retrieval-lab/runs'))).items
