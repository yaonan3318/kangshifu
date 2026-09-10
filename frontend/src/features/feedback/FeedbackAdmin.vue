<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { listFeedback, listFeedbackReasons, resolveFeedback, type FeedbackQuery } from '../../api/feedback'
import { listAssistants } from '../../api/assistants'
import type { AssistantRecord } from '../../types/assistant'
import type { AnswerFeedbackRecord } from '../../types/feedback'
import { errorMessage } from '../../utils/errors'

const items = ref<AnswerFeedbackRecord[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const resolving = ref('')
const notes = ref<Record<string, string>>({})
const assistants = ref<AssistantRecord[]>([])
const reasons = ref<string[]>([])
const showResolved = ref(false)

const pageSize = 30

const filters = reactive({
  rating: '',
  username: '',
  assistant_id: '',
  reason: '',
  no_answer: '',
  document_id: '',
  created_from: '',
  created_to: '',
})

function currentQuery(): FeedbackQuery {
  return {
    rating: filters.rating || undefined,
    resolved: showResolved.value ? true : undefined,
    username: filters.username || undefined,
    assistant_id: filters.assistant_id || undefined,
    reason: filters.reason || undefined,
    no_answer: filters.no_answer === '' ? undefined : filters.no_answer === 'true',
    document_id: filters.document_id || undefined,
    created_from: filters.created_from ? new Date(filters.created_from).toISOString() : undefined,
    created_to: filters.created_to ? new Date(filters.created_to).toISOString() : undefined,
    page: page.value,
    page_size: pageSize,
  }
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const result = await listFeedback(currentQuery())
    items.value = result.items
    total.value = result.total
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取反馈')
  } finally {
    loading.value = false
  }
}

async function loadReference() {
  try {
    const [assistantResult, reasonResult] = await Promise.all([listAssistants(), listFeedbackReasons()])
    assistants.value = assistantResult.items
    reasons.value = reasonResult.items
  } catch {
    // 参考数据失败不阻塞反馈列表。
  }
}

function applyFilters() {
  page.value = 1
  void refresh()
}

function toggleShowResolved() {
  page.value = 1
  void refresh()
}

async function markResolved(item: AnswerFeedbackRecord) {
  resolving.value = item.id
  try {
    await resolveFeedback(item.id, notes.value[item.id] ?? '')
    notes.value[item.id] = ''
    notice.value = '反馈已标记为已处理'
    await refresh()
  } catch (reason) {
    error.value = errorMessage(reason, '处理失败')
  } finally {
    resolving.value = ''
  }
}

function changePage(next: number) {
  page.value = next
  void refresh()
}

function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`
}

onMounted(async () => {
  await loadReference()
  await refresh()
})
</script>

<template>
  <main class="app-shell">
    <header class="hero"><p class="eyebrow">QUALITY · FEEDBACK</p><h1>答案质量反馈</h1><p>查看员工对回答的评价，标记处理并记录解决说明。</p></header>
    <section class="library-panel">
      <div class="section-heading">
        <div><p class="eyebrow">FEEDBACK</p><h2>反馈列表 <span>{{ total }}</span></h2></div>
        <label class="secondary-action" style="cursor:pointer">
          <input type="checkbox" v-model="showResolved" @change="toggleShowResolved" style="margin-right:6px">只看已处理
        </label>
      </div>
      <div class="filter-row">
        <select v-model="filters.rating">
          <option value="">全部评价</option>
          <option value="UP">点赞</option>
          <option value="DOWN">点踩</option>
        </select>
        <select v-model="filters.assistant_id">
          <option value="">全部助手</option>
          <option v-for="assistant in assistants" :key="assistant.id" :value="assistant.id">{{ assistant.name }}</option>
        </select>
        <input v-model="filters.username" placeholder="用户">
        <select v-model="filters.reason">
          <option value="">全部点踩原因</option>
          <option v-for="reason in reasons" :key="reason" :value="reason">{{ reason }}</option>
        </select>
        <select v-model="filters.no_answer">
          <option value="">全部回答</option>
          <option value="true">无答案</option>
          <option value="false">有答案</option>
        </select>
        <input v-model="filters.document_id" placeholder="文档 ID">
        <input v-model="filters.created_from" type="datetime-local">
        <input v-model="filters.created_to" type="datetime-local">
        <button type="button" class="secondary-action" @click="applyFilters">筛选</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="notice" class="assistant-hint">{{ notice }}</p>
      <p v-if="loading" class="empty">加载中…</p>
      <div v-else-if="!items.length" class="empty">暂无反馈</div>
      <ul v-else class="feedback-admin-list">
        <li v-for="item in items" :key="item.id" class="feedback-admin-card">
          <header>
            <div>
              <strong :class="item.rating === 'UP' ? 'is-up' : 'is-down'">{{ item.rating === 'UP' ? '有帮助' : '没帮助' }}</strong>
              <span>{{ item.username || '匿名' }} · {{ item.session_title || '会话' }}</span>
              <span v-if="item.no_answer" class="is-stale">无答案</span>
            </div>
            <small>{{ new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) }}</small>
          </header>
          <p v-if="item.question" class="feedback-question">问：{{ item.question }}</p>
          <p v-if="item.reasons.length" class="feedback-admin-reasons">原因：{{ item.reasons.join('、') }}</p>
          <blockquote v-if="item.answer_content" class="feedback-admin-answer">{{ item.answer_content }}</blockquote>
          <p v-if="item.sources.length" class="feedback-sources">引用：{{ item.sources.map((source) => source.document_name).join('、') }}</p>
          <p class="feedback-meta">
            助手：{{ item.assistant_name || '默认' }} · 模型：{{ item.provider || '—' }} ·
            检索：{{ ms(item.metrics.retrieval_ms) }} · 生成：{{ ms(item.metrics.llm_generation_ms) }}
          </p>
          <p v-if="item.comment" class="feedback-admin-comment">补充：{{ item.comment }}</p>
          <div v-if="!item.resolved_at" class="feedback-admin-actions">
            <input v-model="notes[item.id]" maxlength="2000" placeholder="解决说明（可选）">
            <button type="button" class="secondary-action" :disabled="resolving === item.id" @click="markResolved(item)">标记已处理</button>
          </div>
          <small v-else class="feedback-admin-resolved">已处理：{{ item.resolution_note || '（无说明）' }}</small>
        </li>
      </ul>
      <nav v-if="total > pageSize" class="pagination">
        <button :disabled="page === 1" @click="changePage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
        <button :disabled="page * pageSize >= total" @click="changePage(page + 1)">下一页</button>
      </nav>
    </section>
  </main>
</template>
