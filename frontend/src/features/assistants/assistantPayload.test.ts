import { describe, expect, it } from 'vitest'
import { buildAssistantPayload, type AssistantFormState } from './assistantPayload'

function makeForm(overrides: Partial<AssistantFormState> = {}): AssistantFormState {
  return {
    name: '  技术助手  ',
    description: '',
    avatar: '',
    model_provider: 'ollama',
    model_name: 'qwen3:8b',
    use_deepseek_allowed: true,
    default_deepseek_enabled: false,
    deepseek_enabled: false,
    harness_enabled: false,
    harness_context: '',
    harness_namespace: 'default',
    retrieval_limit: 6,
    temperature: 0.2,
    welcome_message: '',
    system_prompt: '提示词',
    recommended_questions: '问题一\n\n问题二 ',
    answer_template: 'AUTO',
    internet_enabled: false,
    no_answer_policy: 'SUGGEST',
    capabilities: '能做A\n能做B',
    limitations: '',
    chatflow_id: '',
    ...overrides,
  }
}

describe('buildAssistantPayload DeepSeek 开关独立性', () => {
  it('只打开 deepseek_enabled 不会联动其他开关', () => {
    const payload = buildAssistantPayload(makeForm({ deepseek_enabled: true }))
    expect(payload.deepseek_enabled).toBe(true)
    expect(payload.use_deepseek_allowed).toBe(true)
    expect(payload.default_deepseek_enabled).toBe(false)
  })

  it('关闭 use_deepseek_allowed 不会改变实际启用与默认状态', () => {
    const payload = buildAssistantPayload(makeForm({
      use_deepseek_allowed: false, default_deepseek_enabled: true, deepseek_enabled: true,
    }))
    expect(payload.use_deepseek_allowed).toBe(false)
    expect(payload.default_deepseek_enabled).toBe(true)
    expect(payload.deepseek_enabled).toBe(true)
  })

  it('修改默认状态不会影响其他两个开关', () => {
    const payload = buildAssistantPayload(makeForm({
      use_deepseek_allowed: false, default_deepseek_enabled: true, deepseek_enabled: false,
    }))
    expect(payload.default_deepseek_enabled).toBe(true)
    expect(payload.use_deepseek_allowed).toBe(false)
    expect(payload.deepseek_enabled).toBe(false)
  })

  it('Harness 与联网开关不影响 DeepSeek 开关', () => {
    const payload = buildAssistantPayload(makeForm({
      harness_enabled: true, harness_context: 'docker-desktop', internet_enabled: true,
    }))
    expect(payload.harness_enabled).toBe(true)
    expect(payload.internet_enabled).toBe(true)
    expect(payload.use_deepseek_allowed).toBe(true)
    expect(payload.default_deepseek_enabled).toBe(false)
    expect(payload.deepseek_enabled).toBe(false)
  })

  it('Harness 关闭时不提交 context', () => {
    const payload = buildAssistantPayload(makeForm({ harness_enabled: false, harness_context: 'dev' }))
    expect(payload.harness_context).toBeNull()
  })

  it('文本字段被正确清洗', () => {
    const payload = buildAssistantPayload(makeForm())
    expect(payload.name).toBe('技术助手')
    expect(payload.description).toBeNull()
    expect(payload.recommended_questions).toEqual(['问题一', '问题二'])
    expect(payload.capabilities).toEqual(['能做A', '能做B'])
    expect(payload.avatar).toBe('康')
  })

  it('知识库范围：默认不放大到全部知识库', () => {
    expect(buildAssistantPayload(makeForm()).allow_all_knowledge_bases).toBe(false)
    expect(buildAssistantPayload(makeForm(), true).allow_all_knowledge_bases).toBe(true)
  })
})
