import type { QueryRewriteInfo, SearchDiagnostics, SearchResult } from './search'

export interface RetrievalInspect {
  items: SearchResult[]
  diagnostics: SearchDiagnostics
  query_rewrite?: QueryRewriteInfo | null
  queries?: string[]
}

export interface DictionaryEntry {
  id: string
  category: 'SYNONYM' | 'ABBREVIATION' | 'PROPER_NOUN'
  term: string
  expansions: string[]
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface EvaluationSet {
  id: string
  name: string
  description: string | null
  knowledge_base_id: string | null
  enabled: boolean
  case_count: number
  created_at: string
  updated_at: string
}

export interface RetrievalCase {
  id: string
  evaluation_set_id: string | null
  name: string
  question: string
  knowledge_base_id: string | null
  expected_document_ids: string[]
  must_cite_document_ids: string[]
  forbidden_document_ids: string[]
  expected_keywords: string[]
  expected_answer_keypoints: string[]
  expected_no_answer: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ConfigVersion {
  id: string
  name: string
  description: string | null
  config: Record<string, unknown>
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface RetrievalRun {
  id: string
  evaluation_set_id: string | null
  config_version_id: string | null
  settings_snapshot: Record<string, unknown>
  config_snapshot: Record<string, unknown>
  results: Array<Record<string, unknown>>
  metrics: Record<string, number | string>
  created_at: string
}

export interface ConfigDifference {
  field: string
  label: string
  left: unknown
  right: unknown
}

export interface RunCompare {
  left: RetrievalRun
  right: RetrievalRun
  metric_deltas: Record<string, number>
  config_differences: ConfigDifference[]
  case_changes: Array<Record<string, unknown>>
}

export interface CaseImportResult {
  created: number
  skipped: number
  errors: string[]
}
