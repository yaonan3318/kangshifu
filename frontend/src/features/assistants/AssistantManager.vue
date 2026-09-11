<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { listKnowledgeBases } from '../../api/knowledgeBases'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
import { createAssistant, deleteAssistant, setAssistantEnabled, setAssistantKnowledgeBases, updateAssistant } from '../../api/assistants'
import { listAssistants } from '../../api/assistants'
import type { AssistantRecord } from '../../types/assistant'
import { getHarnessStatus, getNamespaces } from '../../api/harness'
import { listChatflows } from '../../api/chatflows'
import type { ChatflowRecord } from '../../types/chatflow'
import { buildAssistantPayload } from './assistantPayload'

const DEFAULT_PROMPT = '你是公司内部知识助手。只能把提供的内部资料作为公司事实依据，用专业、简洁、有引用的中文回答；没有可靠资料时明确说明，不编造公司结论。'

const assistants = ref<AssistantRecord[]>([])
const knowledgeBases = ref<KnowledgeBaseRecord[]>([])
const selectedId = ref('')
const editorOpen = ref(false)
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const useAllKnowledgeBases = ref(true)
const selectedKbIds = ref<string[]>([])
const harnessContexts = ref<string[]>([])
const harnessNamespaces = ref<string[]>(['default'])
const chatflows = ref<ChatflowRecord[]>([])

const selected = computed(() => assistants.value.find((item) => item.id === selectedId.value) ?? null)

const form = reactive({
  name: '',
  description: '',
  avatar: '康',
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
  system_prompt: DEFAULT_PROMPT,
  recommended_questions: '',
  answer_template: 'AUTO',
  internet_enabled: false,
  no_answer_policy: 'SUGGEST',
  capabilities: '',
  limitations: '',
  chatflow_id: '',
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [assistantResult, kbResult, harnessResult, flowResult] = await Promise.all([
      listAssistants(), listKnowledgeBases(), getHarnessStatus().catch(() => null),
      listChatflows().catch(() => [] as ChatflowRecord[]),
    ])
    assistants.value = assistantResult.items
    knowledgeBases.value = kbResult.items
    harnessContexts.value = harnessResult?.contexts ?? []
    chatflows.value = flowResult
    if (selectedId.value && !assistants.value.some((item) => item.id === selectedId.value)) selectedId.value = ''
    if (selected.value && editorOpen.value) applyToForm(selected.value)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function applyToForm(item: AssistantRecord) {
  form.name = item.name
  form.description = item.description || ''
  form.avatar = item.avatar || '康'
  form.model_provider = item.model_provider || 'ollama'
  form.model_name = item.model_name || 'qwen3:8b'
  form.use_deepseek_allowed = item.use_deepseek_allowed
  form.default_deepseek_enabled = item.default_deepseek_enabled
  form.deepseek_enabled = item.deepseek_enabled
  form.harness_enabled = item.harness_enabled
  form.harness_context = item.harness_context || ''
  form.harness_namespace = item.harness_namespace || 'default'
  void refreshHarnessNamespaces()
  form.retrieval_limit = item.retrieval_limit
  form.temperature = item.temperature
  form.welcome_message = item.welcome_message || ''
  form.system_prompt = item.system_prompt || DEFAULT_PROMPT
  form.recommended_questions = (item.recommended_questions || []).join('\n')
  form.answer_template = item.answer_template || 'AUTO'
  form.internet_enabled = Boolean(item.internet_enabled)
  form.no_answer_policy = item.no_answer_policy || 'SUGGEST'
  form.capabilities = (item.capabilities || []).join('\n')
  form.limitations = (item.limitations || []).join('\n')
  form.chatflow_id = item.chatflow_id || ''
  selectedKbIds.value = item.knowledge_base_ids ?? []
  useAllKnowledgeBases.value = Boolean(item.allow_all_knowledge_bases)
}

function selectAssistant(id: string) {
  selectedId.value = id
  const item = assistants.value.find((entry) => entry.id === id)
  if (item) applyToForm(item)
  editorOpen.value = true
}

function newForm() {
  selectedId.value = ''
  form.name = ''
  form.description = ''
  form.avatar = '康'
  form.model_provider = 'ollama'
  form.model_name = 'qwen3:8b'
  form.use_deepseek_allowed = true
  form.default_deepseek_enabled = false
  form.deepseek_enabled = false
  form.harness_enabled = false
  form.harness_context = harnessContexts.value[0] || ''
  form.harness_namespace = 'default'
  form.retrieval_limit = 6
  form.temperature = 0.2
  form.welcome_message = ''
  form.system_prompt = DEFAULT_PROMPT
  form.recommended_questions = ''
  form.answer_template = 'AUTO'
  form.internet_enabled = false
  form.no_answer_policy = 'SUGGEST'
  form.capabilities = ''
  form.limitations = ''
  form.chatflow_id = ''
  selectedKbIds.value = []
  useAllKnowledgeBases.value = false
  editorOpen.value = true
}

function closeEditor() {
  editorOpen.value = false
  selectedId.value = ''
}

function useDefaultPrompt() {
  form.system_prompt = DEFAULT_PROMPT
}

function toggleKnowledgeBase(id: string) {
  const index = selectedKbIds.value.indexOf(id)
  if (index >= 0) selectedKbIds.value.splice(index, 1)
  else selectedKbIds.value.push(id)
}

function onAllKbToggle(event: Event) {
  useAllKnowledgeBases.value = (event.target as HTMLInputElement).checked
}

function resetToSelected() {
  if (selectedId.value) {
    const item = assistants.value.find((entry) => entry.id === selectedId.value)
    if (item) applyToForm(item)
  } else {
    newForm()
  }
}

async function save() {
  if (!form.name.trim()) {
    error.value = '请填写助手名称'
    return
  }
  saving.value = true
  error.value = ''
  const payload = buildAssistantPayload(form, useAllKnowledgeBases.value)
  try {
    let item: AssistantRecord
    if (selectedId.value) {
      item = await updateAssistant(selectedId.value, payload)
      item = await setAssistantKnowledgeBases(item.id, useAllKnowledgeBases.value ? [] : selectedKbIds.value)
    } else {
      item = await createAssistant(payload)
      item = await setAssistantKnowledgeBases(item.id, useAllKnowledgeBases.value ? [] : selectedKbIds.value)
      selectedId.value = item.id
    }
    await refresh()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function refreshHarnessNamespaces() {
  if (!form.harness_context) {
    harnessNamespaces.value = ['default']
    return
  }
  try {
    const values = await getNamespaces(form.harness_context)
    harnessNamespaces.value = values.length ? values : ['default']
    if (!harnessNamespaces.value.includes(form.harness_namespace)) form.harness_namespace = harnessNamespaces.value[0]
  } catch {
    harnessNamespaces.value = [form.harness_namespace || 'default']
  }
}

async function toggle(item: AssistantRecord) {
  try {
    await setAssistantEnabled(item.id, !item.enabled)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '操作失败'
  }
}

async function remove(item: AssistantRecord) {
  if (!window.confirm(`确定删除助手“${item.name}”？此操作不可恢复。`)) return
  try {
    await deleteAssistant(item.id)
    if (selectedId.value === item.id) selectedId.value = ''
    await refresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '删除失败'
  }
}

onMounted(refresh)
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">ASSISTANTS · ROLES</p>
      <h1>助手配置</h1>
      <p>配置不同角色的公司知识助手：每个助手可绑定专属知识库、系统提示词、模型与召回数量。助手只会依据被授权的资料回答。</p>
    </header>
    <p v-if="error" class="error">{{ error }}</p>

    <div class="assistant-admin-layout">
      <section class="assistant-panel assistant-list-panel">
        <div class="section-heading">
          <div><p class="eyebrow">ASSISTANTS</p><h2>助手列表</h2></div>
          <button type="button" class="primary-action" @click="newForm">＋ 新建助手</button>
        </div>
        <p v-if="loading" class="assistant-hint">正在加载…</p>
        <div v-else class="admin-table-wrap">
          <table class="admin-table">
            <thead><tr><th>助手</th><th>职责说明</th><th>模型</th><th>知识库范围</th><th>DeepSeek</th><th>Harness</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="item in assistants" :key="item.id" :class="{ selected: item.id === selectedId }">
                <td><span class="assistant-table-name"><span class="mini-avatar">{{ item.avatar || '康' }}</span><strong>{{ item.name }}</strong></span></td>
                <td class="assistant-description" :title="item.description || ''">{{ item.description || '暂无说明' }}</td>
                <td>{{ item.model_name || '默认' }}</td>
                <td>{{ item.knowledge_base_ids.length === 0 ? '全部知识库' : `${item.knowledge_base_ids.length} 个知识库` }}</td>
                <td>{{ !item.use_deepseek_allowed ? '禁止' : (item.deepseek_enabled ? '开启' : '关闭') }}</td>
                <td>{{ item.harness_enabled ? '开启' : '关闭' }}</td>
                <td><span :class="item.enabled ? 'is-active' : 'is-stale'">{{ item.enabled ? '启用' : '停用' }}</span></td>
                <td class="row-actions">
                  <button type="button" @click="selectAssistant(item.id)">编辑</button>
                  <button type="button" @click="toggle(item)">{{ item.enabled ? '停用' : '启用' }}</button>
                  <button v-if="item.id !== assistants[0]?.id" type="button" class="text-danger" @click="remove(item)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div v-if="editorOpen" class="assistant-editor-backdrop" @click.self="closeEditor">
      <section class="assistant-panel assistant-editor-panel" role="dialog" aria-modal="true" aria-label="助手编辑">
        <div class="section-heading">
          <div><p class="eyebrow">EDITOR</p><h2>{{ selectedId ? '编辑助手' : '新建助手' }}</h2></div>
          <button type="button" class="close-button" aria-label="关闭" @click="closeEditor">×</button>
        </div>
        <form class="assistant-form" @submit.prevent="save">
          <div class="two-col">
            <label class="form-row">名称<input v-model="form.name" type="text" maxlength="255" placeholder="例如：技术资料助手"></label>
            <label class="form-row">头像字符<input v-model="form.avatar" type="text" maxlength="4" placeholder="例如：技"></label>
          </div>
          <label class="form-row">简介<textarea v-model="form.description" rows="2" maxlength="2000" placeholder="一句话介绍助手职责"></textarea></label>
          <div class="two-col">
            <label class="form-row">模型服务<select v-model="form.model_provider"><option value="ollama">本地千问（Ollama）</option><option value="deepseek">DeepSeek</option></select></label>
            <label class="form-row">模型名称<input v-model="form.model_name" type="text" maxlength="255" placeholder="qwen3:8b"></label>
            <label class="form-row">召回片段数量<input v-model.number="form.retrieval_limit" type="number" min="1" max="20"></label>
            <label class="form-row">温度（0~2）<input v-model.number="form.temperature" type="number" min="0" max="2" step="0.05"></label>
          </div>
          <fieldset class="capability-settings">
            <legend>模型与工具能力</legend>
            <label class="capability-option">
              <input v-model="form.use_deepseek_allowed" type="checkbox">
              <span><strong>允许使用 DeepSeek</strong><small>关闭后该助手永久禁用 DeepSeek，即使下面两个开关打开也不会调用。</small></span>
            </label>
            <label class="capability-option">
              <input v-model="form.default_deepseek_enabled" type="checkbox">
              <span><strong>默认启用 DeepSeek</strong><small>新建会话时 DeepSeek 的默认状态；与“允许使用”和“实际启用”互不影响。</small></span>
            </label>
            <label class="capability-option">
              <input v-model="form.deepseek_enabled" type="checkbox">
              <span><strong>实际启用 DeepSeek 增强</strong><small>检索完成后，将允许外发的资料片段交给 DeepSeek 优化答案。</small></span>
            </label>
            <label class="capability-option">
              <input v-model="form.harness_enabled" type="checkbox">
              <span><strong>启用 Harness 运维工具</strong><small>仅管理员使用该助手时生效；Kubernetes 写操作仍需逐次确认。</small></span>
            </label>
            <div v-if="form.harness_enabled" class="harness-policy-grid">
              <label class="form-row">Kubernetes 环境（Context）
                <select v-model="form.harness_context" @change="refreshHarnessNamespaces">
                  <option value="" disabled>请选择已授权环境</option>
                  <option v-for="context in harnessContexts" :key="context" :value="context">{{ context }}</option>
                </select>
              </label>
              <label class="form-row">资源空间（Namespace）
                <select v-model="form.harness_namespace">
                  <option v-for="namespace in harnessNamespaces" :key="namespace" :value="namespace">{{ namespace }}</option>
                </select>
              </label>
              <p v-if="!harnessContexts.length" class="answer-notice is-warning">尚未配置允许的 Kubernetes Context，Harness 暂时不会生效。</p>
            </div>
          </fieldset>
          <label class="form-row">欢迎语<textarea v-model="form.welcome_message" rows="2" maxlength="2000" placeholder="对话空白页展示给用户的欢迎消息"></textarea></label>
          <label class="form-row">推荐问题（每行一个）
            <textarea v-model="form.recommended_questions" rows="3" placeholder="一行一个推荐问题"></textarea>
          </label>
          <label class="form-row">系统提示词
            <textarea v-model="form.system_prompt" rows="6"></textarea>
            <span class="assistant-hint">提示词必须约束助手只依据内部资料并给出 [n] 引用，不允许绕过知识库或权限过滤。</span>
          </label>
          <button type="button" class="secondary-action" style="width:fit-content" @click="useDefaultPrompt">填入安全默认模板</button>

          <div class="two-col">
            <label class="form-row">默认答案模板
              <select v-model="form.answer_template">
                <option value="AUTO">自动识别问题类型</option>
                <option value="POLICY">制度：结论/适用范围/办理步骤/注意事项</option>
                <option value="TECHNICAL">技术：结论/实施步骤/代码或命令/风险</option>
                <option value="PROGRESS">项目进度：时间线/状态/阻塞/下一步</option>
                <option value="COMPARISON">对比：对比表格/差异/建议</option>
                <option value="SUMMARY">汇总：主题归类/关键结论/引用来源</option>
                <option value="GENERAL">通用：直接结论/依据/补充说明</option>
              </select>
            </label>
            <label class="form-row">无答案策略
              <select v-model="form.no_answer_policy">
                <option value="SUGGEST">提示并推荐资料</option>
                <option value="STRICT">严格：只给固定提示</option>
                <option value="GENERAL">允许通用知识补充</option>
              </select>
            </label>
          </div>
          <label class="form-row">绑定流程
            <select v-model="form.chatflow_id">
              <option value="">内置默认流程</option>
              <option v-for="flow in chatflows" :key="flow.id" :value="flow.id">{{ flow.name }}（已发布 v{{ flow.published_version }}）</option>
            </select>
            <span class="assistant-hint">助手问答时按所选流程的节点开关执行；未选择时使用内置默认流程。</span>
          </label>
          <label class="capability-option">
            <input v-model="form.internet_enabled" type="checkbox">
            <span><strong>允许联网</strong><small>为后续联网检索预留的开关；当前版本仅记录策略，不发起联网请求。</small></span>
          </label>
          <div class="two-col">
            <label class="form-row">能做什么（每行一条）<textarea v-model="form.capabilities" rows="3" placeholder="例如：结合技术文档给出实施步骤"></textarea></label>
            <label class="form-row">不能做什么（每行一条）<textarea v-model="form.limitations" rows="3" placeholder="例如：不提供法律意见"></textarea></label>
          </div>

          <div>
            <p class="assistant-hint" style="margin:0 0 6px">知识库范围：专项助手必须显式绑定知识库，未绑定将无法检索。</p>
            <label class="form-row" style="display:flex;align-items:center;gap:8px;flex-direction:row">
              <input type="checkbox" :checked="useAllKnowledgeBases" @change="onAllKbToggle">
              <span>允许访问全部启用知识库（综合助手）</span>
            </label>
            <div v-if="!useAllKnowledgeBases" class="assistant-checkboxes">
              <label v-for="kb in knowledgeBases" :key="kb.id">
                <input type="checkbox" :checked="selectedKbIds.includes(kb.id)" @change="toggleKnowledgeBase(kb.id)">
                {{ kb.name }}{{ kb.enabled ? '' : '（停用）' }}
              </label>
            </div>
            <p v-if="!useAllKnowledgeBases && selectedKbIds.length === 0" class="answer-notice is-warning">
              尚未配置资料范围：该助手不会检索任何知识库，保存后用户端将显示“尚未配置资料范围”。
            </p>
          </div>

          <div class="form-actions">
            <button type="button" class="secondary-action" @click="resetToSelected">重置</button>
            <button type="submit" :disabled="saving || !form.name.trim()">{{ saving ? '保存中…' : '保存助手' }}</button>
          </div>
        </form>
      </section>
      </div>
    </div>
  </main>
</template>
