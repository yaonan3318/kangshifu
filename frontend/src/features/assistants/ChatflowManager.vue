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
    if (!selectedId.value && flows.value.length) selectFlow(flows.value[0].id)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '读取流程失败'
  }
}

function selectFlow(id: string) {
  selectedId.value = id
  const flow = flows.value.find((item) => item.id === id)
  draft.value = flow ? JSON.parse(JSON.stringify(flow.draft_graph)) : null
  dirty.value = false
  debugResult.value = null
  void loadVersions()
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
  const name = window.prompt('流程名称')
  if (!name?.trim()) return
  try {
    const created = await createChatflow({ name: name.trim() })
    await load()
    selectFlow(created.id)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '创建流程失败'
  }
}

async function removeFlow(item: ChatflowRecord) {
  if (!window.confirm(`删除流程“${item.name}”？绑定该流程的助手将回退到内置默认流程。`)) return
  await deleteChatflow(item.id)
  if (selectedId.value === item.id) selectedId.value = ''
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

    <div class="chatflow-layout">
      <section class="assistant-panel chatflow-list">
        <div class="section-heading">
          <div><p class="eyebrow">FLOWS</p><h2>流程列表</h2></div>
          <button type="button" class="primary-action" @click="createFlow">＋ 新建流程</button>
        </div>
        <ul class="governance-list">
          <li v-for="item in flows" :key="item.id" :class="{ selected: item.id === selectedId }">
            <div>
              <strong>{{ item.name }}</strong>
              <small>已发布 v{{ item.published_version }} · 绑定助手 {{ item.bound_assistant_count }}</small>
            </div>
            <div class="row-actions">
              <button type="button" @click="selectFlow(item.id)">编辑</button>
              <button type="button" class="text-danger" @click="removeFlow(item)">删除</button>
            </div>
          </li>
        </ul>
      </section>

      <section v-if="selected && draft" class="assistant-panel chatflow-canvas">
        <div class="section-heading">
          <div><p class="eyebrow">CANVAS</p><h2>{{ selected.name }}</h2></div>
          <div class="row-actions">
            <button type="button" class="secondary-action" :disabled="busy || !dirty" @click="saveDraft">保存草稿</button>
            <button type="button" :disabled="busy" @click="publish">发布版本</button>
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
      </section>
    </div>
  </main>
</template>
