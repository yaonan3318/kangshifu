<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { listFeedback, resolveFeedback } from '../../api/feedback'
import type { AnswerFeedbackRecord } from '../../types/feedback'

const items = ref<AnswerFeedbackRecord[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const showResolved = ref(false)
const resolving = ref('')
const notes = ref<Record<string, string>>({})

const pageSize = 30

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const result = await listFeedback(showResolved.value || undefined, page.value)
    items.value = result.items
    total.value = result.total
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '无法读取反馈'
  } finally {
    loading.value = false
  }
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
    await refresh()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '处理失败'
  } finally {
    resolving.value = ''
  }
}

function changePage(next: number) {
  page.value = next
  void refresh()
}

onMounted(refresh)
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
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="loading" class="empty">加载中…</p>
      <div v-else-if="!items.length" class="empty">暂无反馈</div>
      <ul v-else class="feedback-admin-list">
        <li v-for="item in items" :key="item.id" class="feedback-admin-card">
          <header>
            <div>
              <strong :class="item.rating === 'UP' ? 'is-up' : 'is-down'">{{ item.rating === 'UP' ? '有帮助' : '没帮助' }}</strong>
              <span>{{ item.username || '匿名' }} · {{ item.session_title || '会话' }}</span>
            </div>
            <small>{{ new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) }}</small>
          </header>
          <p v-if="item.reasons.length" class="feedback-admin-reasons">{{ item.reasons.join('、') }}</p>
          <blockquote v-if="item.answer_content" class="feedback-admin-answer">{{ item.answer_content }}</blockquote>
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
        <span>第 {{ page }} 页</span>
        <button :disabled="page * pageSize >= total" @click="changePage(page + 1)">下一页</button>
      </nav>
    </section>
  </main>
</template>
