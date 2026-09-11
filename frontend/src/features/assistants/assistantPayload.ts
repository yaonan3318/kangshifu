// 助手表单 -> API 载荷的纯函数映射；单独抽出以便做前端回归测试，
// 确保三个 DeepSeek 开关与 Harness/联网开关互不联动。

export interface AssistantFormState {
  name: string
  description: string
  avatar: string
  model_provider: string
  model_name: string
  use_deepseek_allowed: boolean
  default_deepseek_enabled: boolean
  deepseek_enabled: boolean
  harness_enabled: boolean
  harness_context: string
  harness_namespace: string
  retrieval_limit: number
  temperature: number
  welcome_message: string
  system_prompt: string
  recommended_questions: string
  answer_template: string
  internet_enabled: boolean
  no_answer_policy: string
  capabilities: string
  limitations: string
  chatflow_id: string
}

export interface AssistantPayload {
  name: string
  description: string | null
  avatar: string
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
  welcome_message: string | null
  system_prompt: string | null
  recommended_questions: string[]
  answer_template: string
  internet_enabled: boolean
  no_answer_policy: string
  capabilities: string[]
  limitations: string[]
  allow_all_knowledge_bases: boolean
  chatflow_id: string | null
}

function lines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}

export function buildAssistantPayload(form: AssistantFormState, allowAllKnowledgeBases = false): AssistantPayload {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    avatar: form.avatar.trim() || '康',
    model_provider: form.model_provider,
    model_name: form.model_name.trim() || null,
    use_deepseek_allowed: form.use_deepseek_allowed,
    default_deepseek_enabled: form.default_deepseek_enabled,
    deepseek_enabled: form.deepseek_enabled,
    harness_enabled: form.harness_enabled,
    harness_context: form.harness_enabled ? form.harness_context || null : null,
    harness_namespace: form.harness_namespace || 'default',
    retrieval_limit: Number(form.retrieval_limit) || 6,
    temperature: Number(form.temperature) ?? 0.2,
    welcome_message: form.welcome_message.trim() || null,
    system_prompt: form.system_prompt.trim() || null,
    recommended_questions: lines(form.recommended_questions),
    answer_template: form.answer_template,
    internet_enabled: form.internet_enabled,
    no_answer_policy: form.no_answer_policy,
    capabilities: lines(form.capabilities),
    limitations: lines(form.limitations),
    allow_all_knowledge_bases: allowAllKnowledgeBases,
    chatflow_id: form.chatflow_id || null,
  }
}
