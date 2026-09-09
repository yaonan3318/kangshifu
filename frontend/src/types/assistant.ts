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
  retrieval_limit: number
  temperature: number
  recommended_questions: string[]
  enabled: boolean
  created_at: string
  updated_at: string
  knowledge_base_ids: string[]
}

export interface AssistantListResponse {
  items: AssistantRecord[]
  total: number
}
