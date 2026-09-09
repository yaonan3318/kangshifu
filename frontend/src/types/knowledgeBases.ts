export interface KnowledgeBaseRecord {
  id: string
  name: string
  description: string | null
  enabled: boolean
  document_count: number
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseList { items: KnowledgeBaseRecord[]; total: number }
