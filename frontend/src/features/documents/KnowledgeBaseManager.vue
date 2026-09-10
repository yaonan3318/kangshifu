<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { createKnowledgeBase, setKnowledgeBaseEnabled, updateKnowledgeBase } from '../../api/knowledgeBases'
import type { ChunkingConfig, ChunkingStrategy, KnowledgeBaseRecord } from '../../types/knowledgeBases'

const props = defineProps<{ items: KnowledgeBaseRecord[] }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const name = ref('')
const description = ref('')
const busy = ref(false)
const error = ref('')
const editingId = ref('')

const STRATEGIES: Array<{ value: ChunkingStrategy; label: string }> = [
  { value: 'fixed', label: '固定长度切片' },
  { value: 'heading', label: '标题层级切片' },
  { value: 'paragraph', label: '段落切片' },
  { value: 'page', label: '页面切片' },
  { value: 'table', label: '表格切片' },
  { value: 'parent_child', label: '父子切片' },
]

const config = reactive<ChunkingConfig>({
  strategy: 'fixed', target: 800, maximum: 1200, overlap: 100, min_chars: 40, row_batch: 30,
})

async function create() {
  if (!name.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    await createKnowledgeBase(name.value.trim(), description.value.trim())
    name.value = ''
    description.value = ''
    emit('changed')
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '创建失败'
  } finally {
    busy.value = false
  }
}

async function toggle(item: KnowledgeBaseRecord) {
  error.value = ''
  try {
    await setKnowledgeBaseEnabled(item.id, !item.enabled)
    emit('changed')
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '操作失败'
  }
}

function openConfig(item: KnowledgeBaseRecord) {
  editingId.value = item.id
  const current = item.chunking_config || {}
  config.strategy = (current.strategy as ChunkingStrategy) || 'fixed'
  config.target = current.target ?? 800
  config.maximum = current.maximum ?? 1200
  config.overlap = current.overlap ?? 100
  config.min_chars = current.min_chars ?? 40
  config.row_batch = current.row_batch ?? 30
}

async function saveConfig() {
  if (!editingId.value) return
  busy.value = true
  error.value = ''
  try {
    await updateKnowledgeBase(editingId.value, { chunking_config: { ...config } })
    editingId.value = ''
    emit('changed')
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '保存切片配置失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="detail-backdrop" @click.self="emit('close')">
    <section class="detail-panel compact-dialog" role="dialog" aria-modal="true">
      <header>
        <div><p class="eyebrow">KNOWLEDGE BASES</p><h2>管理知识库</h2></div>
        <button class="close-button" @click="emit('close')">×</button>
      </header>
      <p v-if="error" class="error">{{ error }}</p>
      <div class="kb-create">
        <label>名称<input v-model="name" placeholder="例如：技术资料库"></label>
        <label>说明<input v-model="description" placeholder="可选"></label>
        <button :disabled="busy || !name.trim()" @click="create">创建</button>
      </div>
      <ul class="governance-list">
        <li v-for="item in props.items" :key="item.id">
          <div><strong>{{ item.name }}</strong><small>{{ item.description || '暂无说明' }} · {{ item.document_count }} 份资料 · 切片 {{ item.chunking_config?.strategy || 'fixed' }}</small></div>
          <div class="row-actions">
            <button @click="openConfig(item)">切片策略</button>
            <button @click="toggle(item)">{{ item.enabled ? '停用' : '启用' }}</button>
          </div>
        </li>
      </ul>

      <section v-if="editingId" class="kb-chunking-editor">
        <p class="eyebrow">CHUNKING</p>
        <h3>切片策略</h3>
        <div class="case-form">
          <label>策略
            <select v-model="config.strategy">
              <option v-for="item in STRATEGIES" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label>目标长度<input v-model.number="config.target" type="number" min="50"></label>
          <label>最大长度<input v-model.number="config.maximum" type="number" min="50"></label>
          <label>重叠长度<input v-model.number="config.overlap" type="number" min="0"></label>
          <label>最小字符数<input v-model.number="config.min_chars" type="number" min="0"></label>
          <label>表格行批次<input v-model.number="config.row_batch" type="number" min="1"></label>
        </div>
        <div class="form-actions">
          <button type="button" class="secondary-action" @click="editingId = ''">取消</button>
          <button type="button" :disabled="busy" @click="saveConfig">保存</button>
        </div>
      </section>
    </section>
  </div>
</template>
