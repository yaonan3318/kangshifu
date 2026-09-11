<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '../../api/documents'
import {
  createChatflow, debugChatflow, deleteChatflow, listChatflowVersions, listChatflows,
  listNodeTypes, publishChatflow, rollbackChatflow, updateChatflow,
} from '../../api/chatflows'
import type {
  ChatflowDebugResult, ChatflowGraph, ChatflowNode, ChatflowRecord, ChatflowVersion, NodeTypeDef,
} from '../../types/chatflow'

const flows = ref<ChatflowRecord[]>([])
const nodeTypes = ref<NodeTypeDef[]>([])
const selectedId = ref('')
const draft = ref<ChatflowGraph | null>(null)
const versions = ref<ChatflowVersion[]>([])
const publishNote = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const debugQuestion = ref('')
const includeGeneration = ref(false)
const debugResult = ref<ChatflowDebugResult | null>(null)
const editorOpen = ref(false)
const creating = ref(false)
const newFlowName = ref('')

const selected = computed(() => flows.value.find((item) => item.id === selectedId.value) ?? null)
const dirty = ref(false)

function nodeDef(type: string): NodeTypeDef | undefined {
  return nodeTypes.value.find((item) => item.type === type)
}

function nodeLabel(node: ChatflowNode): string {
  return nodeDef(node.type)?.label ?? node.type
}

function branchTargets(node: ChatflowNode): string[] {
  const config = node.config as { branches?: Array<{ when: string; next: string }>; default_next?: string }
  const branches = (config.branches ?? []).map((item) => `${item.when} → ${item.next}`)
  if (config.default_next) branches.push(`默认 → ${config.default_next}`)
  return branches
}

async function load() {
  try {
    const [flowList, types] = await Promise.all([listChatflows(), listNodeTypes()])
    flows.value = flowList
    nodeTypes.value = types
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '读取流程失败'
  }
}

function selectFlow(id: string) {
  creating.value = false
  selectedId.value = id
  const flow = flows.value.find((item) => item.id === id)
  draft.value = flow ? JSON.parse(JSON.stringify(flow.draft_graph)) : null
  dirty.value = false
  debugResult.value = null
  editorOpen.value = true
  void loadVersions()
}

function openCreate() {
  selectedId.value = ''
  draft.value = null
  creating.value = true
  newFlowName.value = ''
  error.value = ''
  editorOpen.value = true
}

function closeEditor() {
  editorOpen.value = false
  creating.value = false
  selectedId.value = ''
  draft.value = null
  debugResult.value = null
}

async function loadVersions() {
  if (!selectedId.value) return
  try {
    versions.value = await listChatflowVersions(selectedId.value)
  } catch {
    versions.value = []
  }
}

async function createFlow() {
  const name = newFlowName.value.trim()
  if (!name) { error.value = '请填写流程名称'; return }
  busy.value = true
  error.value = ''
  try {
    const created = await createChatflow({ name })
    await load()
    selectFlow(created.id)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '创建流程失败'
  } finally {
    busy.value = false
  }
}

async function removeFlow(item: ChatflowRecord) {
  if (!window.confirm(`删除流程“${item.name}”？绑定该流程的助手将回退到内置默认流程。`)) return
  await deleteChatflow(item.id)
  if (selectedId.value === item.id) closeEditor()
  await load()
}

function toggleNode(node: ChatflowNode) {
  node.enabled = !node.enabled
  dirty.value = true
}

function updateConfig(node: ChatflowNode, key: string, value: unknown) {
  node.config = { ...node.config, [key]: value }
  dirty.value = true
}

async function saveDraft() {
  if (!selectedId.value || !draft.value) return
  busy.value = true
  error.value = ''
  try {
    await updateChatflow(selectedId.value, { graph: draft.value })
    dirty.value = false
    notice.value = '草稿已保存'
    await load()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '保存草稿失败'
  } finally {
    busy.value = false
  }
}

async function publish() {
  if (!selectedId.value) return
  busy.value = true
  error.value = ''
  try {
    if (dirty.value && draft.value) await updateChatflow(selectedId.value, { graph: draft.value })
    const version = await publishChatflow(selectedId.value, publishNote.value.trim() || null)
    notice.value = `已发布版本 v${version.version}`
    publishNote.value = ''
    await load()
    await loadVersions()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '发布失败'
  } finally {
    busy.value = false
  }
}

async function rollback(version: ChatflowVersion) {
  if (!window.confirm(`回滚到版本 v${version.version}？`)) return
  try {
    await rollbackChatflow(selectedId.value, version.version)
    notice.value = `已回滚到 v${version.version}`
    await load()
    selectFlow(selectedId.value)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '回滚失败'
  }
}

async function runDebug() {
  if (!selectedId.value || !debugQuestion.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    debugResult.value = await debugChatflow(selectedId.value, {
      question: debugQuestion.value.trim(), include_generation: includeGeneration.value,
    })
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '调试失败'
  } finally {
    busy.value = false
  }
}

function statusLabel(status: string): string {
  return { succeeded: '成功', skipped: '跳过', failed: '失败', timeout: '超时' }[status] ?? status
}

onMounted(load)
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">CHATFLOW · FIXED CANVAS</p>
      <h1>流程编排</h1>
      <p>用固定画布配置问答流程节点；草稿与发布版本分离，支持调试运行与历史版本回滚，不同助手可绑定不同流程。</p>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="assistant-hint">{{ notice }}</p>

    <div class="chatflow-admin-layout">
      <section class="assistant-panel chatflow-list-panel">
        <div class="section-heading">
          <div><p class="eyebrow">FLOWS</p><h2>流程列表</h2></div>
          <button type="button" class="primary-action" @click="openCreate">＋ 新建流程</button>
        </div>
        <p v-if="!flows.length" class="assistant-hint">还没有流程，点击“新建流程”开始配置。</p>
        <div v-else class="admin-table-wrap">
          <table class="admin-table">
            <thead><tr><th>流程名称</th><th>说明</th><th>发布版本</th><th>绑定助手</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="item in flows" :key="item.id" :class="{ selected: item.id === selectedId }">
                <td><strong>{{ item.name }}</strong></td>
                <td class="chatflow-description" :title="item.description || ''">{{ item.description || '暂无说明' }}</td>
                <td>v{{ item.published_version }}</td>
                <td>{{ item.bound_assistant_count }}</td>
                <td><span :class="item.enabled ? 'is-active' : 'is-stale'">{{ item.enabled ? '启用' : '停用' }}</span></td>
                <td>{{ new Date(item.updated_at).toLocaleString('zh-CN') }}</td>
                <td class="action-cell"><div class="row-actions">
                  <button type="button" @click="selectFlow(item.id)">编辑</button>
                  <button type="button" class="text-danger" @click="removeFlow(item)">删除</button>
                </div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div v-if="editorOpen" class="chatflow-editor-backdrop" @click.self="closeEditor">
      <section class="assistant-panel chatflow-editor-panel" role="dialog" aria-modal="true" :aria-label="creating ? '新建流程' : '编辑流程'">
        <div v-if="creating" class="chatflow-create-form">
          <div class="section-heading">
            <div><p class="eyebrow">EDITOR</p><h2>新建流程</h2></div>
            <button type="button" class="close-button" aria-label="关闭" @click="closeEditor">×</button>
          </div>
          <label class="form-row">流程名称<input v-model="newFlowName" maxlength="255" placeholder="例如：制度问答流程" @keyup.enter="createFlow"></label>
          <p class="assistant-hint">创建后可继续配置节点、保存草稿并发布版本。</p>
          <div class="form-actions">
            <button type="button" class="secondary-action" @click="closeEditor">取消</button>
            <button type="button" :disabled="busy || !newFlowName.trim()" @click="createFlow">{{ busy ? '创建中…' : '创建流程' }}</button>
          </div>
        </div>

        <template v-else-if="selected && draft">
        <div class="section-heading">
          <div><p class="eyebrow">CANVAS</p><h2>{{ selected.name }}</h2></div>
          <div class="row-actions">
            <button type="button" class="secondary-action" :disabled="busy || !dirty" @click="saveDraft">保存草稿</button>
            <button type="button" :disabled="busy" @click="publish">发布版本</button>
            <button type="button" class="close-button" aria-label="关闭" @click="closeEditor">×</button>
          </div>
        </div>
        <div class="chatflow-nodes">
          <article v-for="node in draft.nodes" :key="node.id" class="chatflow-node" :class="{ disabled: !node.enabled }">
            <header>
              <span class="node-type">{{ nodeLabel(node) }}</span>
              <label class="admin-check-row"><input type="checkbox" :checked="node.enabled" @change="toggleNode(node)"><span>启用</span></label>
            </header>
            <input v-model="node.name" class="node-name" @input="dirty = true">
            <p class="node-next">下一步：{{ node.next || '结束' }}</p>
            <div v-for="field in nodeDef(node.type)?.config_fields ?? []" :key="field.key" class="node-config">
              <label v-if="field.type === 'bool'" class="admin-check-row">
                <input type="checkbox" :checked="Boolean(node.config[field.key])" @change="updateConfig(node, field.key, ($event.target as HTMLInputElement).checked)">
                <span>{{ field.label }}</span>
              </label>
              <label v-else-if="field.type === 'int'" class="form-row">{{ field.label }}
                <input type="number" :value="Number(node.config[field.key] ?? 0)" @change="updateConfig(node, field.key, Number(($event.target as HTMLInputElement).value))">
              </label>
              <ul v-else-if="field.type === 'branches'" class="node-branches">
                <li v-for="branch in branchTargets(node)" :key="branch">{{ branch }}</li>
              </ul>
            </div>
          </article>
        </div>

        <div class="chatflow-versions">
          <div class="section-heading"><div><p class="eyebrow">VERSIONS</p><h2>历史版本</h2></div></div>
          <div class="config-diff">
            <input v-model="publishNote" placeholder="发布说明（可选）">
          </div>
          <ul class="governance-list">
            <li v-for="item in versions" :key="item.id">
              <div><strong>v{{ item.version }}</strong><small>{{ item.note || '无说明' }} · {{ new Date(item.created_at).toLocaleString('zh-CN') }}</small></div>
              <button type="button" @click="rollback(item)">回滚</button>
            </li>
          </ul>
        </div>

        <div class="chatflow-debug">
          <div class="section-heading"><div><p class="eyebrow">DEBUG</p><h2>调试运行</h2></div></div>
          <div class="lab-query">
            <label>测试问题<textarea v-model="debugQuestion" placeholder="输入一个问题，观察每个节点耗时与输出"></textarea></label>
            <label class="admin-check-row"><input v-model="includeGeneration" type="checkbox"><span>同时执行生成节点（本地模型 / DeepSeek / 引用校验）</span></label>
            <button :disabled="busy || !debugQuestion.trim()" @click="runDebug">{{ busy ? '运行中…' : '运行调试' }}</button>
          </div>
          <div v-if="debugResult" class="admin-table-wrap">
            <table class="admin-table">
              <thead><tr><th>节点</th><th>类型</th><th>状态</th><th>耗时(ms)</th><th>输出摘要</th></tr></thead>
              <tbody>
                <tr v-for="node in debugResult.nodes" :key="node.id">
                  <td>{{ node.name }}</td>
                  <td>{{ node.type }}</td>
                  <td><span :class="node.status === 'failed' ? 'is-stale' : 'is-active'">{{ statusLabel(node.status) }}</span></td>
                  <td>{{ node.duration_ms }}</td>
                  <td class="node-output">{{ node.error || JSON.stringify(node.output) }}</td>
                </tr>
              </tbody>
            </table>
            <p class="assistant-hint">总耗时 {{ debugResult.total_ms }} ms</p>
          </div>
        </div>
        </template>
      </section>
      </div>
    </div>
  </main>
</template>
