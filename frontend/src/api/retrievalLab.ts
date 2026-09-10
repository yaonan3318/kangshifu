import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type {
  CaseImportResult, ConfigDifference, ConfigVersion, DictionaryEntry, EvaluationSet,
  RetrievalCase, RetrievalInspect, RetrievalRun, RunCompare,
} from '../types/retrievalLab'

async function parse<T>(response: Promise<Response> | Response): Promise<T> {
  const resolved = await response
  if (resolved.ok) return resolved.status === 204 ? (undefined as T) : resolved.json()
  const body = (await resolved.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code || 'REQUEST_FAILED', body.error?.message || '请求失败', body.error?.details)
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

// ---------------------------------------------------------------- 诊断

export const inspectRetrieval = (query: string, knowledgeBaseId?: string, history: Array<{ question: string; answer: string }> = []): Promise<RetrievalInspect> =>
  parse<RetrievalInspect>(fetch('/api/retrieval-lab/inspect', json('POST', {
    query, knowledge_base_id: knowledgeBaseId || null, limit: 10, history,
  })))

// ---------------------------------------------------------------- 检索词典

export const listDictionaries = async (): Promise<DictionaryEntry[]> =>
  (await parse<{ items: DictionaryEntry[] }>(fetch('/api/retrieval-lab/dictionaries'))).items

export const createDictionaryEntry = (body: { category: string; term: string; expansions: string[]; enabled?: boolean }): Promise<DictionaryEntry> =>
  parse<DictionaryEntry>(fetch('/api/retrieval-lab/dictionaries', json('POST', body)))

export const updateDictionaryEntry = (id: string, body: { term?: string; expansions?: string[]; enabled?: boolean }): Promise<DictionaryEntry> =>
  parse<DictionaryEntry>(fetch(`/api/retrieval-lab/dictionaries/${id}`, json('PATCH', body)))

export const deleteDictionaryEntry = (id: string): Promise<void> =>
  parse<void>(fetch(`/api/retrieval-lab/dictionaries/${id}`, { method: 'DELETE' }))

// ---------------------------------------------------------------- 评测集

export const listEvaluationSets = async (): Promise<EvaluationSet[]> =>
  (await parse<{ items: EvaluationSet[] }>(fetch('/api/retrieval-lab/evaluation-sets'))).items

export const createEvaluationSet = (body: { name: string; description?: string | null; knowledge_base_id?: string | null }): Promise<EvaluationSet> =>
  parse<EvaluationSet>(fetch('/api/retrieval-lab/evaluation-sets', json('POST', body)))

export const deleteEvaluationSet = (id: string): Promise<void> =>
  parse<void>(fetch(`/api/retrieval-lab/evaluation-sets/${id}`, { method: 'DELETE' }))

// ---------------------------------------------------------------- 标准问题

export const listSetCases = async (setId: string): Promise<RetrievalCase[]> =>
  (await parse<{ items: RetrievalCase[] }>(fetch(`/api/retrieval-lab/evaluation-sets/${setId}/cases`))).items

export const createSetCase = (setId: string, body: Record<string, unknown>): Promise<RetrievalCase> =>
  parse<RetrievalCase>(fetch(`/api/retrieval-lab/evaluation-sets/${setId}/cases`, json('POST', body)))

export const deleteCase = (caseId: string): Promise<void> =>
  parse<void>(fetch(`/api/retrieval-lab/cases/${caseId}`, { method: 'DELETE' }))

export const importSetCases = async (setId: string, file: File): Promise<CaseImportResult> => {
  const form = new FormData()
  form.append('file', file)
  return parse<CaseImportResult>(fetch(`/api/retrieval-lab/evaluation-sets/${setId}/import`, { method: 'POST', body: form }))
}

// ---------------------------------------------------------------- 配置版本

export const listConfigVersions = async (): Promise<ConfigVersion[]> =>
  (await parse<{ items: ConfigVersion[] }>(fetch('/api/retrieval-lab/config-versions'))).items

export const createConfigVersion = (body: { name: string; description?: string | null; config: Record<string, unknown>; is_default?: boolean }): Promise<ConfigVersion> =>
  parse<ConfigVersion>(fetch('/api/retrieval-lab/config-versions', json('POST', body)))

export const deleteConfigVersion = (id: string): Promise<void> =>
  parse<void>(fetch(`/api/retrieval-lab/config-versions/${id}`, { method: 'DELETE' }))

export const compareConfigVersions = async (left: string, right: string): Promise<ConfigDifference[]> =>
  (await parse<{ differences: ConfigDifference[] }>(
    fetch(`/api/retrieval-lab/config-versions/compare?left=${left}&right=${right}`),
  )).differences

// ---------------------------------------------------------------- 运行与对比

export const runEvaluation = (body: { evaluation_set_id: string; config_version_id?: string | null; limit?: number; include_answers?: boolean }): Promise<RetrievalRun> =>
  parse<RetrievalRun>(fetch('/api/retrieval-lab/runs', json('POST', body)))

export const listRuns = async (evaluationSetId?: string): Promise<RetrievalRun[]> => {
  const query = evaluationSetId ? `?evaluation_set_id=${evaluationSetId}` : ''
  return (await parse<{ items: RetrievalRun[] }>(fetch(`/api/retrieval-lab/runs${query}`))).items
}

export const compareRuns = (left: string, right: string): Promise<RunCompare> =>
  parse<RunCompare>(fetch(`/api/retrieval-lab/runs/compare?left=${left}&right=${right}`))
