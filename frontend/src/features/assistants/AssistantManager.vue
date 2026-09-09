<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { listKnowledgeBases } from '../../api/knowledgeBases'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
import { createAssistant, deleteAssistant, setAssistantEnabled, setAssistantKnowledgeBases, updateAssistant } from '../../api/assistants'
import { listAssistants } from '../../api/assistants'
import type { AssistantRecord } from '../../types/assistant'

const DEFAULT_PROMPT = '你是公司内部知识助手。只能把提供的内部资料作为公司事实依据，用专业、简洁、有引用的中文回答；没有可靠资料时明确说明，不编造公司结论。'

const assistants = ref<AssistantRecord[]>([])
const knowledgeBases = ref<KnowledgeBaseRecord[]>([])
const selectedId = ref('')
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const useAllKnowledgeBases = ref(true)
const selectedKbIds = ref<string[]>([])

const selected = computed(() => assistants.value.find((item) => item.id === selectedId.value) ?? null)

const form = reactive({
  name: '',
  description: '',
  avatar: '康',
  model_provider: 'ollama',
  model_name: 'qwen3:8b',
  use_deepseek_allowed: true,
  default_deepseek_enabled: false,
  retrieval_limit: 6,
  temperature: 0.2,
  welcome_message: '',
  system_prompt: DEFAULT_PROMPT,
  recommended_questions: '',
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [assistantResult, kbResult] = await Promise.all([listAssistants(), listKnowledgeBases()])
    assistants.value = assistantResult.items
    knowledgeBases.value = kbResult.items
    if (!selectedId.value || !assistants.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = assistants.value[0]?.id ?? ''
    }
    if (selected.value) applyToForm(selected.value)
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
  form.retrieval_limit = item.retrieval_limit
  form.temperature = item.temperature
  form.welcome_message = item.welcome_message || ''
  form.system_prompt = item.system_prompt || DEFAULT_PROMPT
  form.recommended_questions = (item.recommended_questions || []).join('\n')
  selectedKbIds.value = item.knowledge_base_ids ?? []
  useAllKnowledgeBases.value = !(item.knowledge_base_ids?.length)
}

function selectAssistant(id: string) {
  selectedId.value = id
  const item = assistants.value.find((entry) => entry.id === id)
  if (item) applyToForm(item)
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
  form.retrieval_limit = 6
  form.temperature = 0.2
  form.welcome_message = ''
  form.system_prompt = DEFAULT_PROMPT
  form.recommended_questions = ''
  selectedKbIds.value = []
  useAllKnowledgeBases.value = true
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
  const payload = {
    name: form.name.trim(),
    description: form.description.trim() || null,
    avatar: form.avatar.trim() || '康',
    model_provider: form.model_provider,
    model_name: form.model_name.trim() || null,
    use_deepseek_allowed: form.use_deepseek_allowed,
    default_deepseek_enabled: form.default_deepseek_enabled,
    retrieval_limit: Number(form.retrieval_limit) || 6,
    temperature: Number(form.temperature) ?? 0.2,
    welcome_message: form.welcome_message.trim() || null,
    system_prompt: form.system_prompt.trim() || null,
    recommended_questions: form.recommended_questions.split('\n').map((item) => item.trim()).filter(Boolean),
  }
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

    <div class="assistant-grid">
      <section class="assistant-panel">
        <div class="section-heading">
          <div><p class="eyebrow">ASSISTANTS</p><h2>助手列表</h2></div>
          <button type="button" class="primary-action" @click="newForm">＋ 新建助手</button>
        </div>
        <p v-if="loading" class="assistant-hint">正在加载…</p>
        <ul v-else class="assistant-list">
          <li v-for="item in assistants" :key="item.id" :class="{ selected: item.id === selectedId }">
            <header>
              <span class="mini-avatar">{{ item.avatar || '康' }}</span>
              <div style="min-width:0">
                <strong>{{ item.name }}</strong>
                <small v-if="item.description">{{ item.description }}</small>
                <small v-else style="display:block">暂无说明</small>
              </div>
            </header>
            <small>
              模型：{{ item.model_name || '默认' }} ·
              {{ item.knowledge_base_ids.length === 0 ? '全部知识库' : `${item.knowledge_base_ids.length} 个知识库` }} ·
              {{ item.enabled ? '已启用' : '已停用' }}
            </small>
            <div class="row-actions">
              <button type="button" @click="selectAssistant(item.id)">编辑</button>
              <button type="button" @click="toggle(item)">{{ item.enabled ? '停用' : '启用' }}</button>
              <button v-if="item.id !== assistants[0]?.id" type="button" class="text-danger" @click="remove(item)">删除</button>
            </div>
          </li>
        </ul>
      </section>

      <section class="assistant-panel">
        <div class="section-heading"><div><p class="eyebrow">EDITOR</p><h2>{{ selectedId ? '编辑助手' : '新建助手' }}</h2></div></div>
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
          <div class="assistant-checkboxes">
            <label><input v-model="form.use_deepseek_allowed" type="checkbox">允许使用 DeepSeek 外部增强</label>
            <label><input v-model="form.default_deepseek_enabled" type="checkbox">默认开启 DeepSeek（需同时允许）</label>
          </div>
          <label class="form-row">欢迎语<textarea v-model="form.welcome_message" rows="2" maxlength="2000" placeholder="对话空白页展示给用户的欢迎消息"></textarea></label>
          <label class="form-row">推荐问题（每行一个）
            <textarea v-model="form.recommended_questions" rows="3" placeholder="一行一个推荐问题"></textarea>
          </label>
          <label class="form-row">系统提示词
            <textarea v-model="form.system_prompt" rows="6"></textarea>
            <span class="assistant-hint">提示词必须约束助手只依据内部资料并给出 [n] 引用，不允许绕过知识库或权限过滤。</span>
          </label>
          <button type="button" class="secondary-action" style="width:fit-content" @click="useDefaultPrompt">填入安全默认模板</button>

          <div>
            <p class="assistant-hint" style="margin:0 0 6px">知识库范围（空 = 全部启用的知识库）</p>
            <label class="form-row" style="display:flex;align-items:center;gap:8px;flex-direction:row">
              <input type="checkbox" :checked="useAllKnowledgeBases" @change="onAllKbToggle">
              <span>全部启用知识库（不限）</span>
            </label>
            <div v-if="!useAllKnowledgeBases" class="assistant-checkboxes">
              <label v-for="kb in knowledgeBases" :key="kb.id">
                <input type="checkbox" :checked="selectedKbIds.includes(kb.id)" @change="toggleKnowledgeBase(kb.id)">
                {{ kb.name }}{{ kb.enabled ? '' : '（停用）' }}
              </label>
            </div>
          </div>

          <div class="form-actions">
            <button type="button" class="secondary-action" @click="resetToSelected">重置</button>
            <button type="submit" :disabled="saving || !form.name.trim()">{{ saving ? '保存中…' : '保存助手' }}</button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>
