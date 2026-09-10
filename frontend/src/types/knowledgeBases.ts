export type ChunkingStrategy = 'fixed' | 'heading' | 'paragraph' | 'page' | 'table' | 'parent_child'

export interface ChunkingConfig {
  strategy: ChunkingStrategy
  target: number
  maximum: number
  overlap: number
  min_chars: number
  row_batch: number
}

export interface KnowledgeBaseRecord {
  id: string
  name: string
  description: string | null
  enabled: boolean
  document_count: number
  chunking_config: Partial<ChunkingConfig>
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseList { items: KnowledgeBaseRecord[]; total: number }
