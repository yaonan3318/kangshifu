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
}

export interface SearchResponse {
  query: string
  items: SearchResult[]
  total: number
}
