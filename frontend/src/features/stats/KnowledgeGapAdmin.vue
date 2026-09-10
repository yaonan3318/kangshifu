<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import {
  getKnowledgeGapStats, listKnowledgeGaps, rerunKnowledgeGap, updateKnowledgeGap,
} from '../../api/knowledgeGaps'
import type { KnowledgeGap, KnowledgeGapRerun, KnowledgeGapStats } from '../../types/knowledgeGap'

const gaps = ref<KnowledgeGap[]>([])
const stats = ref<KnowledgeGapStats | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = 20
const status = ref('')
const reason = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)
const rerunResult = ref<KnowledgeGapRerun | null>(null)
const editor = reactive<{ id: string; assignee: string; documents: string; note: string }>({
  id: '', assignee: '', documents: '', note: '',
})

const REASON_LABELS: Record<string, string> = {
  NO_ANSWER: '未找到答案',
  LOW_CONFIDENCE: '低置信度',
  NEGATIVE_FEEDBACK: '用户没帮助',
  WRONG_DOCUMENT: '引用/文档不正确',
  PERMISSION_RESTRICTED: '有资料但无权访问',
}
const STATUS_LABELS: Record<string, string> = {
  OPEN: '待处理', ASSIGNED: '已指派', RESOLVED: '已解决', IGNORED: '已忽略',
}

async function refresh() {
  error.value = ''
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) })
    if (status.value) params.set('status', status.value)
    if (reason.value) params.set('reason', reason.value)
    const [list, statistics] = await Promise.all([listKnowledgeGaps(params), getKnowledgeGapStats()])
    gaps.value = list.items
    total.value = list.total
    stats.value = statistics
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '读取知识缺口失败'
  }
}

function openEditor(gap: KnowledgeGap) {
  editor.id = gap.id
  editor.assignee = gap.assignee_user_id ?? ''
  editor.documents = gap.linked_document_ids.join(',')
  editor.note = gap.note ?? ''
}

async function saveEditor() {
  if (!editor.id) return
  busy.value = true
  try {
    const documents = editor.documents.split(/[,，;；\s]+/).map((item) => item.trim()).filter(Boolean)
    await updateKnowledgeGap(editor.id, {
      assignee_user_id: editor.assignee.trim() || null,
      linked_document_ids: documents,
      note: editor.note.trim() || null,
    })
    notice.value = '已保存处理信息'
    editor.id = ''
    await refresh()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '保存失败'
  } finally {
    busy.value = false
  }
}

async function setStatus(gap: KnowledgeGap, next: string) {
  try {
    await updateKnowledgeGap(gap.id, { status: next })
    await refresh()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '更新状态失败'
  }
}

async function rerun(gap: KnowledgeGap) {
  busy.value = true
  error.value = ''
  try {
    rerunResult.value = await rerunKnowledgeGap(gap.id)
    await refresh()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '重新运行失败'
  } finally {
    busy.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">KNOWLEDGE GAPS</p>
      <h1>知识缺口中心</h1>
      <p>自动沉淀未答、低置信度、负反馈与召回错误的问题；管理员可指派负责人、补充资料、重新运行并对比修复前后答案。</p>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="assistant-hint">{{ notice }}</p>

    <section class="library-panel">
      <div class="section-heading">
        <div><p class="eyebrow">SUMMARY</p><h2>缺口概览</h2></div>
        <div class="run-controls">
          <select v-model="status" @change="refresh"><option value="">全部状态</option><option value="OPEN">待处理</option><option value="ASSIGNED">已指派</option><option value="RESOLVED">已解决</option><option value="IGNORED">已忽略</option></select>
          <select v-model="reason" @change="refresh"><option value="">全部原因</option><option v-for="(label, key) in REASON_LABELS" :key="key" :value="key">{{ label }}</option></select>
        </div>
      </div>
      <div v-if="stats" class="metric-grid">
        <div><b>{{ stats.total }}</b><span>缺口总数</span></div>
        <div><b>{{ stats.open }}</b><span>待处理</span></div>
        <div><b>{{ stats.assigned }}</b><span>已指派</span></div>
        <div><b>{{ stats.resolved }}</b><span>已解决</span></div>
      </div>
    </section>

    <section class="library-panel">
      <div class="admin-table-wrap">
        <table class="admin-table">
          <thead><tr><th>问题</th><th>原因</th><th>次数</th><th>状态</th><th>负责人</th><th>最近出现</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-if="!gaps.length"><td colspan="7" class="empty">暂无知识缺口</td></tr>
            <tr v-for="gap in gaps" :key="gap.id">
              <td class="gap-question">{{ gap.question }}</td>
              <td>{{ REASON_LABELS[gap.reason] ?? gap.reason }}</td>
              <td>{{ gap.count }}</td>
              <td><span :class="gap.status === 'RESOLVED' ? 'is-active' : 'is-stale'">{{ STATUS_LABELS[gap.status] ?? gap.status }}</span></td>
              <td>{{ gap.assignee_user_id || '—' }}</td>
              <td>{{ new Date(gap.last_seen_at).toLocaleString('zh-CN') }}</td>
              <td class="row-actions">
                <button type="button" @click="openEditor(gap)">处理</button>
                <button type="button" :disabled="busy" @click="rerun(gap)">重新运行</button>
                <button v-if="gap.status !== 'RESOLVED'" type="button" @click="setStatus(gap, 'RESOLVED')">解决</button>
                <button v-else type="button" @click="setStatus(gap, 'OPEN')">重开</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="editor.id" class="library-panel">
      <div class="section-heading"><div><p class="eyebrow">HANDLE</p><h2>处理缺口</h2></div></div>
      <div class="case-form">
        <input v-model="editor.assignee" placeholder="负责人用户 ID（可选，UUID）">
        <input v-model="editor.documents" placeholder="关联正确文档 ID，逗号分隔">
        <input v-model="editor.note" placeholder="处理说明">
        <button :disabled="busy" @click="saveEditor">保存</button>
        <button class="secondary-action" @click="editor.id = ''">取消</button>
      </div>
    </section>

    <section v-if="rerunResult" class="library-panel">
      <div class="section-heading"><div><p class="eyebrow">RERUN</p><h2>修复前后对比</h2></div></div>
      <p class="assistant-hint">问题：{{ rerunResult.question }} · 引用 {{ rerunResult.source_count }} 条 · 置信度 {{ (rerunResult.confidence as any)?.label || '—' }}</p>
      <div class="stats-columns">
        <div><p class="eyebrow">修复前</p><pre class="rerun-text">{{ rerunResult.before || '（无历史答案）' }}</pre></div>
        <div><p class="eyebrow">重新运行后</p><pre class="rerun-text">{{ rerunResult.after || '（无答案）' }}</pre></div>
      </div>
    </section>
  </main>
</template>
