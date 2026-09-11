export interface AssistantRecord {
  id: string
  name: string
  description: string | null
  avatar: string
  welcome_message: string | null
  system_prompt: string | null
  model_provider: string
  model_name: string | null
  use_deepseek_allowed: boolean
  default_deepseek_enabled: boolean
  deepseek_enabled: boolean
  harness_enabled: boolean
  harness_context: string | null
  harness_namespace: string
  retrieval_limit: number
  temperature: number
  recommended_questions: string[]
  answer_template: string
  internet_enabled: boolean
  no_answer_policy: string
  capabilities: string[]
  limitations: string[]
  allow_all_knowledge_bases: boolean
  chatflow_id: string | null
  enabled: boolean
  created_at: string
  updated_at: string
  knowledge_base_ids: string[]
}

export interface AssistantWelcome {
  id: string
  name: string
  avatar: string
  description: string | null
  welcome_message: string | null
  capabilities: string[]
  limitations: string[]
  recommended_questions: string[]
  recent_questions: string[]
  knowledge_bases: Array<{ id: string; name: string }>
  knowledge_scope: string
  knowledge_scope_configured: boolean
  general_knowledge_allowed: boolean
  operations_allowed: boolean
  internet_enabled: boolean
  internet_configured: boolean
}

export interface AssistantListResponse {
  items: AssistantRecord[]
  total: number
}
