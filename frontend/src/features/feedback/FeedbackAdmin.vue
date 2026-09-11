<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import {
  assignFeedbackCase, feedbackStatistics, getFeedbackCase, listFeedbackCases,
  updateFeedbackCase, verifyFeedbackCase, type FeedbackCaseQuery,
} from '../../api/feedback'
import { listAssistants } from '../../api/assistants'
import { listKnowledgeBases } from '../../api/knowledgeBases'
import { listUsers } from '../../api/identity'
import type { AssistantRecord } from '../../types/assistant'
import type {
  FeedbackCaseDetail, FeedbackCaseStatus, FeedbackCaseSummary, FeedbackStatistics,
} from '../../types/feedback'
import { errorMessage } from '../../utils/errors'

type TabKey = FeedbackCaseStatus | 'STATS'

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'PENDING', label: '待处理' },
  { key: 'PROCESSING', label: '处理中' },
  { key: 'WAIT_VERIFY', label: '等待复验' },
  { key: 'RESOLVED', label: '已解决' },
  { key: 'IGNORED', label: '已忽略' },
  { key: 'STATS', label: '数据分析' },
]

const STATUS_LABELS: Record<string, string> = {
  PENDING: '待处理', PROCESSING: '处理中', WAIT_VERIFY: '等待复验',
  RESOLVED: '已解决', IGNORED: '已忽略',
}
const PRIORITY_LABELS: Record<string, string> = {
  LOW: '低', NORMAL: '普通', HIGH: '高', URGENT: '紧急',
}
const TYPE_LABELS: Record<string, string> = { UP: '点赞', DOWN: '点踩', REPORT: '举报' }
const VERIFY_LABELS: Record<string, string> = {
  NOT_RUN: '未运行', RUNNING: '运行中', PASSED: '通过', FAILED: '未通过', ERROR: '异常',
}

const tab = ref<TabKey>('PENDING')
const items = ref<FeedbackCaseSummary[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busyId = ref('')
const pageSize = 20

const assistants = ref<AssistantRecord[]>([])
const knowledgeBases = ref<Array<{ id: string; name: string }>>([])
const users = ref<Array<{ id: string; display_name: string }>>([])

const detail = ref<FeedbackCaseDetail | null>(null)
const detailLoading = ref(false)
const caseNote = ref('')
const caseConclusion = ref('')
const assigneeId = ref('')
const priority = ref('NORMAL')
const verifyConclusion = ref('')

const statistics = ref<FeedbackStatistics | null>(null)
const statsLoading = ref(false)

const filters = reactive({
  feedback_type: '', knowledge_base_id: '', assistant_id: '', assignee_id: '',
  keyword: '', created_from: '', created_to: '',
})

const isStats = computed(() => tab.value === 'STATS')

function query(): FeedbackCaseQuery {
  return {
    status: isStats.value ? undefined : [tab.value as string],
    feedback_type: filters.feedback_type || undefined,
    knowledge_base_id: filters.knowledge_base_id || undefined,
    assistant_id: filters.assistant_id || undefined,
    assignee_id: filters.assignee_id || undefined,
    keyword: filters.keyword || undefined,
    created_from: filters.created_from ? new Date(filters.created_from).toISOString() : undefined,
    created_to: filters.created_to ? new Date(filters.created_to).toISOString() : undefined,
    page: page.value,
    page_size: pageSize,
  }
}

async function refresh() {
  if (isStats.value) {
    await loadStatistics()
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await listFeedbackCases(query())
    items.value = result.items
    total.value = result.total
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取反馈工单')
  } finally {
    loading.value = false
  }
}

async function loadStatistics() {
  statsLoading.value = true
  error.value = ''
  try {
    statistics.value = await feedbackStatistics({
      knowledge_base_id: filters.knowledge_base_id || undefined,
      assistant_id: filters.assistant_id || undefined,
    })
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取反馈统计')
  } finally {
    statsLoading.value = false
  }
}

async function loadReference() {
  try {
    const [assistantResult, kbResult, userResult] = await Promise.all([
      listAssistants(), listKnowledgeBases(), listUsers({ page_size: 200 }),
    ])
    assistants.value = assistantResult.items
    knowledgeBases.value = kbResult.items.map((item) => ({ id: item.id, name: item.name }))
    users.value = userResult.items.map((item) => ({ id: item.id, display_name: item.display_name }))
  } catch {
    // 参考数据失败不阻塞队列。
  }
}

function switchTab(key: TabKey) {
  tab.value = key
  page.value = 1
  void refresh()
}

function applyFilters() {
  page.value = 1
  void refresh()
}

async function openDetail(item: FeedbackCaseSummary) {
  busyId.value = item.id
  detailLoading.value = true
  try {
    const result = await getFeedbackCase(item.id)
    detail.value = result
    caseNote.value = result.admin_note ?? ''
    caseConclusion.value = result.conclusion ?? ''
    assigneeId.value = result.assignee_id ?? ''
    priority.value = result.priority
    verifyConclusion.value = ''
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取工单详情')
  } finally {
    detailLoading.value = false
    busyId.value = ''
  }
}

function closeDetail() {
  detail.value = null
}

async function runAction(action: () => Promise<FeedbackCaseDetail>, successText: string) {
  if (!detail.value) return
  busyId.value = detail.value.id
  error.value = ''
  notice.value = ''
  try {
    detail.value = await action()
    notice.value = successText
    await refresh()
  } catch (reason) {
    error.value = errorMessage(reason, '操作失败')
  } finally {
    busyId.value = ''
  }
}

const startProcessing = () => runAction(
  () => updateFeedbackCase(detail.value!.id, { status: 'PROCESSING' }), '已开始处理',
)
const markWaitVerify = () => runAction(
  () => updateFeedbackCase(detail.value!.id, { status: 'WAIT_VERIFY' }), '已标记等待复验',
)
const resolveCase = () => runAction(
  () => updateFeedbackCase(detail.value!.id, { status: 'RESOLVED', conclusion: caseConclusion.value }), '已标记解决',
)
const ignoreCase = () => {
  if (!window.confirm('确认忽略该反馈？忽略后不计入排序与质量统计。')) return
  void runAction(() => updateFeedbackCase(detail.value!.id, { status: 'IGNORED' }), '已忽略')
}
const saveNote = () => runAction(
  () => updateFeedbackCase(detail.value!.id, { admin_note: caseNote.value }), '备注已保存',
)
const saveAssignment = () => runAction(
  () => assignFeedbackCase(detail.value!.id, {
    assignee_id: assigneeId.value || null, priority: priority.value,
  }), '负责人与优先级已更新',
)
const verifyCase = () => runAction(
  () => verifyFeedbackCase(detail.value!.id, verifyConclusion.value || undefined), '复验完成',
)

function openDocument(documentId: string) {
  window.dispatchEvent(new CustomEvent('company-switch-page', { detail: 'library' }))
  window.setTimeout(() => {
    window.dispatchEvent(new CustomEvent('company-open-document', { detail: documentId }))
  }, 0)
}

function openRetrievalLab() {
  if (!detail.value?.question) return
  window.localStorage.setItem('company-search:retrieval-lab-query', detail.value.question)
  window.dispatchEvent(new CustomEvent('company-switch-page', { detail: 'lab' }))
}

function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function metric(value: number | null | undefined, suffix = ''): string {
  if (value === null || value === undefined) return '—'
  return `${value}${suffix}`
}

function rate(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function changePage(next: number) {
  page.value = next
  void refresh()
}

onMounted(async () => {
  await loadReference()
  await refresh()
})
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">QUALITY · FEEDBACK</p>
      <h1>反馈管理</h1>
      <p>处理员工负反馈，跟踪复验与运营统计。</p>
    </header>

    <section class="library-panel">
      <nav class="detail-tabs" aria-label="反馈状态">
        <button
          v-for="item in TABS"
          :key="item.key"
          :class="{ active: tab === item.key }"
          @click="switchTab(item.key)"
        >{{ item.label }}</button>
      </nav>

      <div class="filter-row">
        <select v-model="filters.feedback_type" @change="applyFilters">
          <option value="">全部类型</option>
          <option value="DOWN">点踩</option>
          <option value="REPORT">举报</option>
          <option value="UP">点赞</option>
        </select>
        <select v-model="filters.knowledge_base_id" @change="applyFilters">
          <option value="">全部知识库</option>
          <option v-for="kb in knowledgeBases" :key="kb.id" :value="kb.id">{{ kb.name }}</option>
        </select>
        <select v-model="filters.assistant_id" @change="applyFilters">
          <option value="">全部助手</option>
          <option v-for="assistant in assistants" :key="assistant.id" :value="assistant.id">{{ assistant.name }}</option>
        </select>
        <select v-model="filters.assignee_id" @change="applyFilters">
          <option value="">全部负责人</option>
          <option v-for="user in users" :key="user.id" :value="user.id">{{ user.display_name }}</option>
        </select>
        <input v-model="filters.keyword" placeholder="关键词" @keyup.enter="applyFilters">
        <input v-model="filters.created_from" type="datetime-local">
        <input v-model="filters.created_to" type="datetime-local">
        <button type="button" class="secondary-action" @click="applyFilters">筛选</button>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="notice" class="assistant-hint">{{ notice }}</p>

      <template v-if="!isStats">
        <p v-if="loading" class="empty">加载中…</p>
        <div v-else-if="!items.length" class="empty">当前分类下暂无反馈工单</div>
        <div v-else class="table-scroll">
          <table class="data-table">
            <thead>
              <tr>
                <th>问题摘要</th><th>类型</th><th>原因</th><th>用户</th><th>助手</th>
                <th>知识库</th><th>状态</th><th>优先级</th><th>负责人</th>
                <th>创建时间</th><th>最近复验</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.id">
                <td class="wrap-cell">{{ item.question || '（无问题快照）' }}</td>
                <td><span :class="item.feedback_type === 'UP' ? 'is-up' : 'is-down'">{{ TYPE_LABELS[item.feedback_type] }}</span></td>
                <td>{{ item.reasons.join('、') || '—' }}</td>
                <td>{{ item.username || '匿名' }}</td>
                <td>{{ assistants.find((a) => a.id === item.assistant_id)?.name || '—' }}</td>
                <td>{{ item.knowledge_base_ids.length }}</td>
                <td>{{ STATUS_LABELS[item.status] }}</td>
                <td>{{ PRIORITY_LABELS[item.priority] }}</td>
                <td>{{ users.find((u) => u.id === item.assignee_id)?.display_name || '未分配' }}</td>
                <td>{{ formatTime(item.created_at) }}</td>
                <td>{{ item.last_verification_result ? VERIFY_LABELS[item.last_verification_result] : '—' }}</td>
                <td>
                  <button type="button" class="secondary-action" :disabled="busyId === item.id" @click="openDetail(item)">详情</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <nav v-if="total > pageSize" class="pagination">
          <button :disabled="page === 1" @click="changePage(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
          <button :disabled="page * pageSize >= total" @click="changePage(page + 1)">下一页</button>
        </nav>
      </template>

      <template v-else>
        <p v-if="statsLoading" class="empty">加载中…</p>
        <div v-else-if="statistics">
          <div class="metric-grid">
            <div class="metric-card"><small>反馈总数</small><strong>{{ metric(statistics.overall.feedback_count) }}</strong></div>
            <div class="metric-card"><small>有帮助</small><strong>{{ metric(statistics.overall.helpful_count) }}</strong></div>
            <div class="metric-card"><small>没帮助</small><strong>{{ metric(statistics.overall.unhelpful_count) }}</strong></div>
            <div class="metric-card"><small>满意率</small><strong>{{ rate(statistics.overall.satisfaction_rate) }}</strong></div>
            <div class="metric-card"><small>无答案率</small><strong>{{ rate(statistics.overall.no_answer_rate) }}</strong></div>
            <div class="metric-card"><small>待处理</small><strong>{{ metric(statistics.overall.pending_count) }}</strong></div>
            <div class="metric-card"><small>平均处理时长</small><strong>{{ metric(statistics.overall.avg_handling_hours, 'h') }}</strong></div>
            <div class="metric-card"><small>复验通过率</small><strong>{{ rate(statistics.overall.verification_pass_rate) }}</strong></div>
          </div>

          <h3>知识库维度</h3>
          <div class="table-scroll">
            <table class="data-table">
              <thead><tr><th>知识库</th><th>反馈数</th><th>有帮助</th><th>没帮助</th><th>满意率</th><th>无答案率</th><th>待处理</th></tr></thead>
              <tbody>
                <tr v-for="row in statistics.knowledge_bases" :key="String(row.knowledge_base_id)">
                  <td>{{ row.knowledge_base_name || row.knowledge_base_id }}</td>
                  <td>{{ metric(row.feedback_count as number) }}</td>
                  <td>{{ metric(row.helpful_count as number) }}</td>
                  <td>{{ metric(row.unhelpful_count as number) }}</td>
                  <td>{{ rate(row.satisfaction_rate as number) }}</td>
                  <td>{{ rate(row.no_answer_rate as number) }}</td>
                  <td>{{ metric(row.pending_count as number) }}</td>
                </tr>
                <tr v-if="!statistics.knowledge_bases.length"><td colspan="7" class="empty">暂无数据</td></tr>
              </tbody>
            </table>
          </div>

          <h3>助手维度</h3>
          <div class="table-scroll">
            <table class="data-table">
              <thead><tr><th>助手</th><th>反馈数</th><th>满意率</th><th>无答案率</th><th>待处理</th></tr></thead>
              <tbody>
                <tr v-for="row in statistics.assistants" :key="String(row.assistant_id)">
                  <td>{{ row.assistant_name || row.assistant_id }}</td>
                  <td>{{ metric(row.feedback_count as number) }}</td>
                  <td>{{ rate(row.satisfaction_rate as number) }}</td>
                  <td>{{ rate(row.no_answer_rate as number) }}</td>
                  <td>{{ metric(row.pending_count as number) }}</td>
                </tr>
                <tr v-if="!statistics.assistants.length"><td colspan="5" class="empty">暂无数据</td></tr>
              </tbody>
            </table>
          </div>

          <h3>检索配置版本维度</h3>
          <div class="table-scroll">
            <table class="data-table">
              <thead><tr><th>配置版本</th><th>反馈数</th><th>满意率</th><th>没帮助</th><th>复验通过率</th></tr></thead>
              <tbody>
                <tr v-for="row in statistics.config_versions" :key="String(row.config_version_id)">
                  <td>{{ row.config_version_name || row.config_version_id }}</td>
                  <td>{{ metric(row.feedback_count as number) }}</td>
                  <td>{{ rate(row.satisfaction_rate as number) }}</td>
                  <td>{{ metric(row.unhelpful_count as number) }}</td>
                  <td>{{ rate(row.verification_pass_rate as number) }}</td>
                </tr>
                <tr v-if="!statistics.config_versions.length"><td colspan="5" class="empty">暂无数据</td></tr>
              </tbody>
            </table>
          </div>

          <h3>片段级反馈聚合</h3>
          <p class="assistant-hint">反馈排序开关：{{ statistics.enabled ? '已启用' : '未启用' }}，最少不同用户数 {{ statistics.parameters.feedback_min_distinct_users }}，最大提升 {{ statistics.parameters.feedback_max_positive_boost }}，最大惩罚 {{ statistics.parameters.feedback_max_negative_penalty }}。</p>
          <div class="table-scroll">
            <table class="data-table">
              <thead><tr><th>片段</th><th>问题指纹</th><th>正向用户</th><th>负向用户</th><th>调整</th></tr></thead>
              <tbody>
                <tr v-for="row in statistics.aggregates" :key="String(row.chunk_id) + String(row.query_fingerprint)">
                  <td>{{ String(row.chunk_id).slice(0, 8) }}…</td>
                  <td>{{ String(row.query_fingerprint).slice(0, 10) }}…</td>
                  <td>{{ metric(row.positive_users as number) }}</td>
                  <td>{{ metric(row.negative_users as number) }}</td>
                  <td>{{ Number(row.feedback_boost ?? 0).toFixed(4) }}</td>
                </tr>
                <tr v-if="!statistics.aggregates.length"><td colspan="5" class="empty">暂无聚合数据</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </section>

    <div v-if="detail || detailLoading" class="drawer-backdrop" @click.self="closeDetail">
      <aside class="feedback-drawer">
        <header>
          <div>
            <p class="eyebrow">CASE</p>
            <h2>{{ detail ? STATUS_LABELS[detail.status] : '加载中…' }}</h2>
          </div>
          <button type="button" class="secondary-action" @click="closeDetail">关闭</button>
        </header>
        <p v-if="detailLoading" class="empty">加载中…</p>
        <template v-else-if="detail">
          <section>
            <h3>原始问题</h3>
            <p>{{ detail.question || '（无）' }}</p>
          </section>
          <section>
            <h3>回答对比</h3>
            <div class="compare-grid">
              <div>
                <h4>反馈时回答</h4>
                <blockquote>{{ detail.answer_snapshot || '—' }}</blockquote>
              </div>
              <div>
                <h4>最近复验回答</h4>
                <blockquote>{{ detail.verifications[0]?.after_answer || '尚未复验' }}</blockquote>
              </div>
            </div>
          </section>
          <section>
            <h3>引用资料与片段</h3>
            <ul class="feedback-source-list">
              <li v-for="source in detail.documents" :key="source.chunk_id">
                <button type="button" class="link-button" @click="openDocument(source.document_id)">{{ source.document_name }}</button>
                <span>引用版本 {{ source.feedback_version ?? '—' }} / 当前版本 {{ source.current_version ?? '—' }}</span>
                <span v-if="source.deleted" class="is-stale">已删除</span>
                <span v-else-if="!source.enabled" class="is-stale">已停用</span>
                <p>{{ source.content_snapshot }}</p>
              </li>
            </ul>
          </section>
          <section>
            <h3>用户原因与评论</h3>
            <p>类型：{{ TYPE_LABELS[detail.feedback_type] }} · 原因：{{ detail.reasons.join('、') || '—' }}</p>
            <p>{{ detail.comment || '（无评论）' }}</p>
            <p class="assistant-hint">检索配置版本：{{ detail.retrieval_config_version_id || '—' }} · 模型：{{ detail.answer_model || detail.answer_provider || '—' }}</p>
          </section>

          <section>
            <h3>处理</h3>
            <div class="filter-row">
              <select v-model="assigneeId">
                <option value="">未分配</option>
                <option v-for="user in users" :key="user.id" :value="user.id">{{ user.display_name }}</option>
              </select>
              <select v-model="priority">
                <option v-for="(label, key) in PRIORITY_LABELS" :key="key" :value="key">{{ label }}</option>
              </select>
              <button type="button" class="secondary-action" :disabled="busyId === detail.id" @click="saveAssignment">保存分配</button>
            </div>
            <textarea v-model="caseNote" rows="2" placeholder="管理员备注"></textarea>
            <button type="button" class="secondary-action" :disabled="busyId === detail.id" @click="saveNote">保存备注</button>
            <textarea v-model="caseConclusion" rows="2" placeholder="处理结论"></textarea>
            <div class="feedback-actions">
              <button type="button" class="secondary-action" :disabled="busyId === detail.id" @click="startProcessing">开始处理</button>
              <button type="button" class="secondary-action" :disabled="busyId === detail.id" @click="markWaitVerify">等待复验</button>
              <button type="button" class="primary-action" :disabled="busyId === detail.id" @click="resolveCase">标记已解决</button>
              <button type="button" class="danger-action" :disabled="busyId === detail.id" @click="ignoreCase">忽略</button>
            </div>
          </section>

          <section>
            <h3>复验</h3>
            <textarea v-model="verifyConclusion" rows="2" placeholder="复验结论（可选）"></textarea>
            <div class="feedback-actions">
              <button type="button" class="primary-action" :disabled="busyId === detail.id" @click="verifyCase">重新运行原问题</button>
              <button type="button" class="secondary-action" @click="openRetrievalLab">在检索实验室分析</button>
            </div>
            <ul class="feedback-timeline">
              <li v-for="run in detail.verifications" :key="run.id">
                <strong>{{ VERIFY_LABELS[run.status] }}</strong>
                <span>{{ formatTime(run.created_at) }} · 耗时 {{ ms(run.duration_ms) }} · 无答案：{{ run.no_answer ? '是' : '否' }}</span>
                <p v-if="run.error_message" class="error">{{ run.error_message }}</p>
              </li>
            </ul>
          </section>

          <section>
            <h3>处理记录</h3>
            <ul class="feedback-timeline">
              <li v-for="event in detail.events" :key="event.id">
                <strong>{{ event.event_type }}</strong>
                <span>{{ event.from_status || '—' }} → {{ event.to_status || '—' }} · {{ formatTime(event.created_at) }}</span>
                <p v-if="event.note">{{ event.note }}</p>
              </li>
            </ul>
          </section>
        </template>
      </aside>
    </div>
  </main>
</template>
