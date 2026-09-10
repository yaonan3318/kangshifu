export interface ChatflowNode {
  id: string
  type: string
  name: string
  enabled: boolean
  config: Record<string, unknown>
  next: string | null
}

export interface ChatflowGraph {
  nodes: ChatflowNode[]
  start_node_id: string
}

export interface ChatflowRecord {
  id: string
  name: string
  description: string | null
  draft_graph: ChatflowGraph
  published_graph: ChatflowGraph
  published_version: number
  enabled: boolean
  bound_assistant_count: number
  created_at: string
  updated_at: string
}

export interface ChatflowVersion {
  id: string
  chatflow_id: string
  version: number
  graph: ChatflowGraph
  note: string | null
  created_at: string
}

export interface NodeConfigField {
  key: string
  type: string
  label: string
}

export interface NodeTypeDef {
  type: string
  label: string
  category: string
  config_fields: NodeConfigField[]
}

export interface ChatflowDebugNode {
  id: string
  type: string
  name: string
  status: 'succeeded' | 'skipped' | 'failed'
  duration_ms: number
  output: Record<string, unknown>
  error: string | null
}

export interface ChatflowDebugResult {
  nodes: ChatflowDebugNode[]
  total_ms: number
  final: Record<string, unknown> | null
}
