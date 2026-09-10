export type MatchType = 'keyword' | 'vector' | 'hybrid'

export interface SearchResult {
  chunk_id: string
  document_id: string
  document_name: string
  extension: string
  sequence_number: number
  content: string
  page_start: number | null
  page_end: number | null
  slide_number: number | null
  sheet_name: string | null
  row_start: number | null
  row_end: number | null
  section_path: string[]
  ocr_confidence: number | null
  match_type: MatchType
  keyword_score: number | null
  vector_score: number | null
  fusion_score: number
  rerank_score: number | null
  final_score: number
  base_score?: number | null
  feedback_boost?: number
}

export interface RetrievalStageItem { chunk_id:string;document_id:string;document_name:string;sequence_number:number;score:number;content_preview:string }
export interface SearchDiagnostics { normalized_query:string;expanded_terms:string[];mode:string;warning:string|null;no_answer_reason:string|null;timings_ms:Record<string,number>;stages:Record<string,RetrievalStageItem[]> }

export interface SearchResponse {
  query: string
  items: SearchResult[]
  total: number
  diagnostics: SearchDiagnostics
}
