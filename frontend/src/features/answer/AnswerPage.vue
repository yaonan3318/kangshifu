<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ApiError } from '../../api/documents'
import { cancelAnswerJob, getActiveAnswerJob, getAnswerStatus, resumeAnswerJob, streamAnswer, warmUpAnswer } from '../../api/answer'
import type { AnswerEvent, AnswerMetrics, AnswerSource, AnswerStatus, AnswerTurn, CitationSource } from '../../types/answer'
import { listKnowledgeBases } from '../../api/knowledgeBases'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
import { getAssistantWelcome, listAssistants } from '../../api/assistants'
import type { AssistantRecord, AssistantWelcome } from '../../types/assistant'
import { submitFeedback } from '../../api/feedback'
import { confirmApproval, getHarnessTask, rejectApproval, resumeHarness } from '../../api/harness'
import { archiveChatSession, createChatSession, deleteChatSession, downloadAnswerPdf, getChatSession, listChatSessions, renameChatSession, restoreChatSession } from '../../api/chat'
import type { ChatMessageRecord, ChatSessionDetail, ChatSessionItem } from '../../types/chat'
import type { HarnessApproval } from '../../types/answer'
import MarkdownView from '../../components/MarkdownView.vue'
import SessionSidebar from './SessionSidebar.vue'
import ReferenceDrawer from './ReferenceDrawer.vue'
import HarnessTimeline from './HarnessTimeline.vue'
import HarnessApprovalCard from './HarnessApproval.vue'

const ACTIVE_SESSION_KEY = 'company-search-active-session'
const DRAFT_KEY = 'company-search-draft'
const question = ref('')
const approvalBusy = ref(false)
const advancedOpen = ref(false)
const status = ref<AnswerStatus | null>(null)
const statusError = ref('')
const knowledgeBases = ref<KnowledgeBaseRecord[]>([])
const knowledgeBaseId = ref('')
const assistants = ref<AssistantRecord[]>([])
const currentAssistantId = ref('')
const currentAssistant = computed(() => assistants.value.find((item) => item.id === currentAssistantId.value) ?? assistants.value[0] ?? null)
const assistantAvatar = computed(() => currentAssistant.value?.avatar || '康')
const assistantWelcome = ref<AssistantWelcome | null>(null)
const generalKnowledgeAllowed = computed(() => Boolean(currentAssistant.value?.use_deepseek_allowed && currentAssistant.value?.deepseek_enabled))

const sessions = ref<ChatSessionItem[]>([])
const sessionsLoading = ref(false)
const sessionError = ref('')
const showArchived = ref(false)
const sessionSearch = ref('')

const activeSessionId = ref<string | null>(null)
const sessionCache = reactive<Record<string, AnswerTurn[]>>({})
const activeSessionTitle = ref('')
const loadingSession = ref(false)

const activeController = ref<AbortController | null>(null)
const scrollPane = ref<HTMLElement | null>(null)
const composerInput = ref<HTMLTextAreaElement | null>(null)

const selectedCitation = ref<CitationSource | null>(null)
const warmed = ref(false)
const warming = ref(false)
let searchTimer: number | undefined

const activeTurns = computed(() => (activeSessionId.value ? sessionCache[activeSessionId.value] ?? [] : []))

const kbName = computed(() => {
  const match = knowledgeBases.value.find((item) => item.id === knowledgeBaseId.value)
  return match ? match.name : null
})
const enabledBases = computed(() => knowledgeBases.value.filter((item) => item.enabled))
const ollamaReady = computed(() => Boolean(status.value?.ollama.reachable && status.value?.ollama.installed))
const scopeLabel = computed(() => {
  if (kbName.value) return kbName.value
  const assistant = currentAssistant.value
  if (assistant) {
    if (assistant.knowledge_base_ids.length === 1) {
      return knowledgeBases.value.find((item) => item.id === assistant.knowledge_base_ids[0])?.name || '已限定知识库'
    }
    if (assistant.knowledge_base_ids.length > 1) return `已限定 ${assistant.knowledge_base_ids.length} 个知识库`
  }
  return '全部知识库'
})

const stageLabels: Record<string, string> = {
  understanding: '正在理解问题',
  rewriting: '正在改写检索问题',
  retrieving: '正在检索公司资料',
  candidates: '正在筛选候选片段',
  reranking: '正在筛选最相关资料',
  local_generating: '正在组织答案',
  deepseek_enhancing: '正在组织答案（DeepSeek）',
  checking: '正在核对引用',
}

function stageText(turn: AnswerTurn): string {
  const stage = turn.stage ?? 'understanding'
  const detail = turn.stageDetail ?? {}
  if (stage === 'retrieving' && detail.knowledge_base_count) {
    return `正在检索 ${detail.knowledge_base_count} 个知识库`
  }
  if (stage === 'candidates' && typeof detail.candidate_count === 'number') {
    return `找到 ${detail.candidate_count} 个候选片段`
  }
  return stageLabels[stage] ?? '正在生成'
}

async function loadStatus() {
  try {
    status.value = await getAnswerStatus()
    statusError.value = ''
    if (ollamaReady.value && !warmed.value) {
      warmed.value = true
      void warmUpModel(false)
    }
  } catch (reason) {
    statusError.value = reason instanceof ApiError ? reason.message : '无法检查本地模型状态'
  }
}

async function warmUpModel(manual: boolean) {
  if (warming.value) return
  warming.value = true
  try {
    await warmUpAnswer()
  } catch {
    if (manual) statusError.value = '本地模型预热失败，请确认 Ollama 已启动'
  } finally {
    warming.value = false
  }
}

async function loadKnowledgeBases() {
  try {
    const result = await listKnowledgeBases()
    knowledgeBases.value = result.items
  } catch {
    // 知识库不影响问答主流程
  }
}

async function loadAssistants() {
  try {
    const result = await listAssistants(true)
    assistants.value = result.items
    if (!currentAssistantId.value && assistants.value.length) {
      currentAssistantId.value = assistants.value[0].id
    }
    await loadAssistantWelcome()
  } catch {
    // 助手列表不可用不影响基本问答
  }
}

async function loadAssistantWelcome() {
  if (!currentAssistantId.value) {
    assistantWelcome.value = null
    return
  }
  try {
    assistantWelcome.value = await getAssistantWelcome(currentAssistantId.value)
  } catch {
    assistantWelcome.value = null
  }
}

watch(currentAssistantId, () => { void loadAssistantWelcome() })

function storeActiveSession(id: string | null) {
  if (id) window.localStorage.setItem(ACTIVE_SESSION_KEY, id)
  else window.localStorage.removeItem(ACTIVE_SESSION_KEY)
}

async function refreshSessions() {
  sessionsLoading.value = true
  try {
    const result = await listChatSessions(sessionSearch.value || undefined, showArchived.value)
    sessions.value = result.items
  } catch (reason) {
    sessionError.value = reason instanceof Error ? reason.message : '无法读取历史会话'
  } finally {
    sessionsLoading.value = false
  }
}

function ensureTurns(sessionId: string): AnswerTurn[] {
  if (!sessionCache[sessionId]) sessionCache[sessionId] = []
  return sessionCache[sessionId]
}

function dbSourceToUi(source: { citation_number: number; document_id: string; chunk_id: string; document_name: string; content_snapshot: string | null; location_snapshot: Record<string, unknown>; score?: number | null; available: boolean; status: string; message?: string | null; version_number?: number | null; cited_version?: number | null; matched_keywords?: string[]; can_download?: boolean; extension?: string | null; retrieval_rank?: number | null; pre_rerank_rank?: number | null; post_rerank_rank?: number | null }): CitationSource {
  const location = source.location_snapshot
  const locationText = (typeof location.text === 'string' && location.text) || '片段内容'
  return {
    citation_number: source.citation_number,
    document_id: source.document_id,
    chunk_id: source.chunk_id,
    document_name: source.document_name,
    content: source.content_snapshot,
    location_text: locationText,
    score: source.score ?? null,
    available: source.available,
    can_download: source.can_download ?? false,
    extension: source.extension ?? null,
    version_number: source.version_number ?? null,
    matched_keywords: source.matched_keywords ?? [],
    retrieval_rank: source.retrieval_rank ?? null,
    pre_rerank_rank: source.pre_rerank_rank ?? null,
    post_rerank_rank: source.post_rerank_rank ?? null,
    cited_version: source.cited_version ?? null,
    status: (source.status as CitationSource['status']) || 'ACTIVE',
    message: source.message ?? null,
    meta: source.location_snapshot,
  }
}

function sseSourceToUi(source: AnswerSource): CitationSource {
  const locationText = source.page_start
    ? `第 ${source.page_start}${source.page_end && source.page_end !== source.page_start ? `–${source.page_end}` : ''} 页`
    : source.slide_number
      ? `第 ${source.slide_number} 张幻灯片`
      : source.sheet_name
        ? `${source.sheet_name}${source.row_start ? ` · 第 ${source.row_start} 行起` : ''}`
        : `片段 ${source.sequence_number}`
  return {
    citation_number: source.citation_number,
    document_id: source.document_id,
    chunk_id: source.chunk_id,
    document_name: source.document_name,
    content: source.content,
    location_text: locationText,
    score: source.score ?? null,
    available: true,
    can_download: true,
    extension: source.extension,
    version_number: source.document_version ?? null,
    cited_version: source.document_version ?? null,
    retrieval_rank: source.retrieval_rank ?? null,
    pre_rerank_rank: source.pre_rerank_rank ?? null,
    post_rerank_rank: source.post_rerank_rank ?? null,
    status: 'ACTIVE',
    meta: {
      page_start: source.page_start, page_end: source.page_end, slide_number: source.slide_number,
      sheet_name: source.sheet_name, row_start: source.row_start, row_end: source.row_end,
      sequence_number: source.sequence_number, section_path: source.section_path, extension: source.extension,
      match_type: source.match_type,
    },
  }
}

function turnFromHistory(messages: ChatMessageRecord[]): AnswerTurn[] {
  const turns: AnswerTurn[] = []
  let pending: AnswerTurn | null = null
  for (const message of messages) {
    if (message.role === 'USER') {
      pending = {
        key: message.id,
        userMessageId: message.id,
        assistantMessageId: null,
        question: message.content,
        answer: '',
        sources: [],
        warnings: [],
        provider: 'LOCAL',
        scope: null,
        generating: false,
        stage: null,
        failed: false,
        stopped: false,
        harnessTaskId: null,
        harnessSteps: [],
        approval: null,
      }
    } else if (message.role === 'ASSISTANT') {
      const hasContent = Boolean(message.content)
      const turn: AnswerTurn = pending ?? {
        key: message.id,
        userMessageId: null,
        assistantMessageId: message.id,
        question: '',
        answer: '',
        sources: [],
        warnings: [],
        provider: message.provider ?? 'LOCAL',
        scope: null,
        generating: false,
        stage: null,
        failed: false,
        stopped: false,
        harnessTaskId: null,
        harnessSteps: [],
        approval: null,
      }
      turn.assistantMessageId = message.id
      turn.answer = message.content || ''
      turn.provider = message.provider ?? 'LOCAL'
      turn.scope = message.knowledge_scope as AnswerTurn['scope']
      turn.metrics = (message.metrics ?? {}) as AnswerMetrics
      turn.confidence = turn.metrics.confidence ?? null
      turn.citationCheck = turn.metrics.citation_check ?? null
      turn.noAnswer = turn.metrics.no_answer ?? null
      turn.questionType = turn.metrics.question_type_label ?? null
      turn.sources = message.sources.map(dbSourceToUi)
      if (message.status === 'FAILED') {
        turn.failed = true
        turn.errorMessage = message.error_message || undefined
      } else if (message.status === 'STOPPED') {
        turn.stopped = true
      } else if (message.status === 'GENERATING') {
        // P2-5：生成中的消息保留，页面加载后通过活动任务恢复；有部分内容先展示。
        turn.generating = true
        turn.stage = turn.stage || 'generating'
        if (hasContent) turn.answer = message.content
        turns.push(turn)
        pending = null
        continue
      }
      turns.push(turn)
      pending = null
    }
  }
  if (pending) {
    pending.stopped = true
    turns.push(pending)
  }
  return turns
}

async function selectSession(sessionId: string) {
  const cached = sessionCache[sessionId]
  if (cached) {
    // 会话已在内存中时直接切换，避免打断正在进行的生成或丢失已生成的部分文本。
    activeSessionId.value = sessionId
    storeActiveSession(sessionId)
    const item = sessions.value.find((entry) => entry.id === sessionId)
    if (item) activeSessionTitle.value = item.title
    return
  }
  await loadSession(sessionId)
}

async function loadSession(sessionId: string, refreshMeta = true) {
  loadingSession.value = true
  try {
    const detail: ChatSessionDetail = await getChatSession(sessionId)
    sessionCache[sessionId] = turnFromHistory(detail.messages)
    activeSessionId.value = sessionId
    activeSessionTitle.value = detail.title
    if (detail.assistant_id) currentAssistantId.value = detail.assistant_id
    storeActiveSession(sessionId)
    if (refreshMeta) await refreshSessions()
    await nextTick()
    scrollToBottom(false)
    void resumeActiveJob(sessionId)
  } catch (reason) {
    sessionError.value = reason instanceof ApiError ? reason.message : '无法恢复会话'
  } finally {
    loadingSession.value = false
  }
}

async function newSession() {
  if (activeController.value) return
  try {
    const detail = await createChatSession(undefined, currentAssistantId.value || undefined)
    sessionCache[detail.id] = []
    activeSessionId.value = detail.id
    activeSessionTitle.value = detail.title
    storeActiveSession(detail.id)
    question.value = ''
    await refreshSessions()
  } catch (reason) {
    sessionError.value = reason instanceof ApiError ? reason.message : '无法新建会话'
  }
}

async function restoreInitialSession() {
  await refreshSessions()
  const stored = window.localStorage.getItem(ACTIVE_SESSION_KEY)
  const list = sessions.value
  const candidate = stored && !showArchived.value ? list.find((item) => item.id === stored) : undefined
  const fallback = list[0]
  const target = candidate ?? fallback
  if (target) await loadSession(target.id, false)
}

async function renameSession(id: string, title: string) {
  try {
    const detail = await renameChatSession(id, title)
    if (id === activeSessionId.value) activeSessionTitle.value = detail.title
    await refreshSessions()
  } catch (reason) {
    sessionError.value = reason instanceof Error ? reason.message : '重命名失败'
  }
}

async function archiveSession(id: string) {
  try {
    await archiveChatSession(id)
    if (id === activeSessionId.value) {
      activeSessionId.value = null
      storeActiveSession(null)
    }
    await refreshSessions()
  } catch (reason) {
    sessionError.value = reason instanceof Error ? reason.message : '归档失败'
  }
}

async function restoreArchivedSession(id: string) {
  try {
    await restoreChatSession(id)
    await refreshSessions()
  } catch (reason) {
    sessionError.value = reason instanceof Error ? reason.message : '恢复失败'
  }
}

async function purgeSession(id: string) {
  try {
    await deleteChatSession(id, true)
    if (id === activeSessionId.value) {
      activeSessionId.value = null
      storeActiveSession(null)
    }
    delete sessionCache[id]
    await refreshSessions()
  } catch (reason) {
    sessionError.value = reason instanceof Error ? reason.message : '删除失败'
  }
}

function historyFor(questionIndex: number): Pick<AnswerTurn, 'question' | 'answer'>[] {
  const turns = activeTurns.value.slice(0, questionIndex).filter((item) => item.answer)
  return turns.slice(-6).map((item) => ({ question: item.question, answer: item.answer }))
}

async function ask(suggested?: string) {
  const value = (suggested ?? question.value).trim()
  if (!value || activeController.value) return
  let sessionId = activeSessionId.value
  if (!sessionId) {
    try {
      const detail = await createChatSession(undefined, currentAssistantId.value || undefined)
      sessionId = detail.id
      sessionCache[detail.id] = []
      activeSessionId.value = detail.id
      activeSessionTitle.value = detail.title
      storeActiveSession(detail.id)
    } catch {
      sessionError.value = '无法创建会话，请检查本地服务'
      return
    }
  }

  const turns = ensureTurns(sessionId)
  const history = historyFor(turns.length)
  const questionIndex = turns.length
  const turn = reactive<AnswerTurn>({
    key: `q-${sessionId}-${Date.now()}`,
    userMessageId: null,
    assistantMessageId: null,
    question: value,
    answer: '',
    sources: [],
    warnings: [],
    provider: 'LOCAL',
    scope: null,
    generating: true,
    stage: 'understanding',
    failed: false,
    stopped: false,
    jobId: null,
    cursor: 0,
    harnessTaskId: null,
    harnessSteps: [],
    approval: null,
  })
  turns.push(turn)
  activeSessionId.value = sessionId
  storeActiveSession(sessionId)
  question.value = ''
  window.localStorage.removeItem(DRAFT_KEY)
  const controller = new AbortController()
  activeController.value = controller
  await scrollToBottom(true)
  try {
    const outcome = await streamAnswer({
      question: value,
      sessionId,
      assistantId: currentAssistantId.value || undefined,
      knowledgeBaseId: knowledgeBaseId.value || undefined,
      useDeepseek: currentAssistant.value?.deepseek_enabled ?? false,
      useHarness: currentAssistant.value?.harness_enabled ?? false,
      k8sContext: currentAssistant.value?.harness_context ?? undefined,
      k8sNamespace: currentAssistant.value?.harness_namespace ?? undefined,
      history,
      requestId: newRequestId(),
    }, controller.signal, (event) => {
      handleAnswerEvent(turn, event)
      void scrollToBottom(false)
    }, (started) => {
      if (started.sessionId) {
        activeSessionId.value = started.sessionId
        storeActiveSession(started.sessionId)
      }
      if (started.messageId) turn.assistantMessageId = started.messageId
      if (started.jobId) turn.jobId = started.jobId
    })
    if (outcome.sessionId) {
      activeSessionId.value = outcome.sessionId
      storeActiveSession(outcome.sessionId)
    }
    if (outcome.messageId) turn.assistantMessageId = outcome.messageId
    if (outcome.jobId) turn.jobId = outcome.jobId
    finalizeTurn(turn, false)
  } catch (reason) {
    if (!controller.signal.aborted) {
      turn.warnings.push({ code: 'CONNECTION_FAILED', message: reason instanceof Error ? reason.message : '问答连接中断' })
      turn.errorMessage = reason instanceof Error ? reason.message : '问答连接中断'
      finalizeTurn(turn, true)
    } else {
      turn.stopped = true
      finalizeTurn(turn, false)
    }
  } finally {
    activeController.value = null
  }
}

function finalizeTurn(turn: AnswerTurn, failed: boolean) {
  if (turn.generating) {
    turn.generating = false
    turn.stage = null
    if (failed) turn.failed = true
    if (!turn.answer && !failed) turn.stopped = true
    void refreshSessions()
  }
}

function newRequestId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function resumeActiveJob(sessionId: string) {
  if (activeController.value) return
  let job
  try {
    job = await getActiveAnswerJob(sessionId)
  } catch {
    return
  }
  if (!job) {
    // 没有活动任务：把历史里遗留的“生成中”标记为失败，避免界面一直转圈。
    const stale = ensureTurns(sessionId).find((item) => item.generating)
    if (stale) {
      stale.generating = false
      stale.failed = true
      stale.errorMessage = '生成任务已中断，请重新生成'
      void refreshSessions()
    }
    return
  }
  const turns = ensureTurns(sessionId)
  let turn = turns.find((item) => item.assistantMessageId === job.message_id)
  if (!turn) {
    turn = turns[turns.length - 1]
  }
  if (!turn) return
  turn.generating = true
  turn.stopped = false
  turn.failed = false
  turn.stage = job.current_stage || 'understanding'
  turn.jobId = job.id
  turn.answer = job.partial_content || turn.answer
  turn.cursor = job.event_cursor || 0
  const controller = new AbortController()
  activeController.value = controller
  try {
    await resumeAnswerJob(job.id, turn.cursor || 0, controller.signal, (event) => {
      handleAnswerEvent(turn!, event)
      void scrollToBottom(false)
    })
    finalizeTurn(turn, false)
    await loadSession(sessionId, false)
  } catch (reason) {
    if (!controller.signal.aborted) {
      turn.warnings.push({ code: 'CONNECTION_FAILED', message: reason instanceof Error ? reason.message : '生成连接中断' })
      finalizeTurn(turn, true)
    }
  } finally {
    activeController.value = null
  }
}

async function regenerate(turn: AnswerTurn) {
  if (activeController.value || !activeSessionId.value) return
  const turns = activeTurns.value
  const index = turns.findIndex((item) => item.key === turn.key)
  const questionIndex = index >= 0 ? index : turns.length
  const history = turns.slice(0, questionIndex).filter((item) => item.answer).slice(-6).map((item) => ({ question: item.question, answer: item.answer }))
  const assistantMessageId = turn.assistantMessageId
  if (!assistantMessageId) return
  turn.answer = ''
  turn.sources = []
  turn.warnings = []
  turn.provider = 'LOCAL'
  turn.scope = null
  turn.generating = true
  turn.stage = 'understanding'
  turn.failed = false
  turn.stopped = false
  turn.errorMessage = undefined
  const controller = new AbortController()
  activeController.value = controller
  await scrollToBottom(true)
  try {
    const outcome = await streamAnswer({
      question: turn.question,
      sessionId: activeSessionId.value,
      assistantId: currentAssistantId.value || undefined,
      regenerateMessageId: assistantMessageId,
      knowledgeBaseId: knowledgeBaseId.value || undefined,
      useDeepseek: currentAssistant.value?.deepseek_enabled ?? false,
      useHarness: currentAssistant.value?.harness_enabled ?? false,
      k8sContext: currentAssistant.value?.harness_context ?? undefined,
      k8sNamespace: currentAssistant.value?.harness_namespace ?? undefined,
      history,
      requestId: newRequestId(),
    }, controller.signal, (event) => {
      handleAnswerEvent(turn, event)
      void scrollToBottom(false)
    }, (started) => {
      if (started.sessionId) {
        activeSessionId.value = started.sessionId
        storeActiveSession(started.sessionId)
      }
      if (started.messageId) turn.assistantMessageId = started.messageId
      if (started.jobId) turn.jobId = started.jobId
    })
    if (outcome.messageId) turn.assistantMessageId = outcome.messageId
    if (outcome.jobId) turn.jobId = outcome.jobId
    finalizeTurn(turn, false)
  } catch (reason) {
    if (!controller.signal.aborted) {
      turn.warnings.push({ code: 'CONNECTION_FAILED', message: reason instanceof Error ? reason.message : '问答连接中断' })
      turn.errorMessage = reason instanceof Error ? reason.message : '问答连接中断'
      finalizeTurn(turn, true)
    } else {
      turn.stopped = true
      finalizeTurn(turn, false)
    }
  } finally {
    activeController.value = null
  }
}

function handleAnswerEvent(turn: AnswerTurn, event: AnswerEvent) {
  handleHarnessEvent(turn, event)
  if (event.type === 'stage') {
    turn.stage = event.stage ?? null
    turn.stageDetail = event.detail ?? null
  }
  if (event.type === 'suggestions' && event.suggestions) turn.suggestions = event.suggestions
  if (event.type === 'sources') turn.sources = (event.sources ?? []).map(sseSourceToUi)
  if (event.type === 'metrics' && event.metrics) turn.metrics = event.metrics
  if (event.type === 'query_rewrite' && event.query_rewrite) {
    turn.metrics = {
      ...(turn.metrics ?? {}),
      retrieval_query: event.query_rewrite.retrieval_query,
      retrieval_queries: event.query_rewrite.queries,
    }
  }
  if (event.type === 'confidence' && event.confidence) {
    turn.confidence = event.confidence
    if (event.question_type) turn.questionType = event.question_type
  }
  if (event.type === 'citation_check' && event.citation_check) turn.citationCheck = event.citation_check
  if (event.type === 'no_answer' && event.no_answer) turn.noAnswer = event.no_answer
  if (event.type === 'replace') { turn.answer = ''; turn.cursor = 0; turn.provider = event.provider ?? 'DEEPSEEK' }
  if (event.type === 'delta') {
    turn.answer += event.text ?? ''
    turn.cursor = (turn.cursor ?? 0) + (event.text?.length ?? 0)
    if (event.provider) turn.provider = event.provider
  }
  if (event.type === 'warning' && event.warning) turn.warnings.push(event.warning)
  if (event.type === 'done') {
    turn.scope = event.scope ?? null
    if (event.provider) turn.provider = event.provider
  }
  if (event.type === 'error' && event.error) {
    turn.warnings.push(event.error)
    turn.errorMessage = event.error.message
  }
}

function handleHarnessEvent(turn: AnswerTurn, event: AnswerEvent) {
  if (event.task_id) turn.harnessTaskId = event.task_id
  if (event.type === 'tool_requested' && event.tool && event.step) {
    turn.harnessSteps.push({ number: event.step, tool: event.tool, status: 'requested', reason: String(event.tool_result?.reason || '') })
  }
  if (event.type === 'tool_running') {
    const step = turn.harnessSteps.find((item) => item.number === event.step)
    if (step) step.status = 'running'
  }
  if (event.type === 'tool_result') {
    const step = turn.harnessSteps.find((item) => item.number === event.step)
    if (step) {
      step.status = event.tool_result?.success === false ? 'failed' : 'succeeded'
      step.result = event.tool_result ?? undefined
    }
  }
  if (event.type === 'approval_required' && event.approval) {
    turn.approval = event.approval
    turn.stage = null
    turn.generating = false
    window.localStorage.setItem('company-search-pending-harness-task', turn.harnessTaskId || '')
    const step = turn.harnessSteps.find((item) => item.number === event.step)
    if (step) step.status = 'awaiting'
  }
  if (event.type === 'harness_done') {
    turn.scope = 'INTERNAL'
    turn.provider = 'HARNESS'
    window.localStorage.removeItem('company-search-pending-harness-task')
  }
}

async function decideApproval(turn: AnswerTurn, confirmation: string | null) {
  if (!turn.approval || !turn.harnessTaskId) return
  approvalBusy.value = true
  try {
    if (confirmation === null) await rejectApproval(turn.approval.id)
    else await confirmApproval(turn.approval.id, confirmation)
    turn.approval = null
    window.localStorage.removeItem('company-search-pending-harness-task')
    turn.generating = true
    await resumeHarness(turn.harnessTaskId, currentAssistant.value?.deepseek_enabled ?? false, (event) => {
      handleHarnessEvent(turn, event)
      if (event.type === 'delta') { turn.answer += event.text ?? ''; if (event.provider) turn.provider = event.provider }
      if (event.type === 'replace') { turn.answer = ''; turn.provider = event.provider ?? 'DEEPSEEK' }
      if (event.type === 'warning' && event.warning) turn.warnings.push(event.warning)
      if (event.type === 'error' && event.error) { turn.warnings.push(event.error); turn.errorMessage = event.error.message }
      if (event.type === 'harness_done') {
        turn.generating = false
        turn.stage = null
        turn.scope = 'INTERNAL'
        turn.provider = 'HARNESS'
        void refreshSessions()
      }
    })
    finalizeTurn(turn, false)
  } catch (reason) {
    turn.warnings.push({ code: 'APPROVAL_FAILED', message: reason instanceof Error ? reason.message : '审批处理失败' })
    finalizeTurn(turn, true)
  } finally {
    approvalBusy.value = false
  }
}

function stop() {
  // 只断开本地 SSE 连接，不取消服务端生成任务（切换页面/标签不应中断生成）。
  activeController.value?.abort()
}

async function cancelGeneration() {
  const turn = activeTurns.value.find((item) => item.generating)
  const jobId = turn?.jobId
  activeController.value?.abort()
  if (jobId) {
    try {
      await cancelAnswerJob(jobId)
    } catch {
      // 取消失败不阻塞界面；服务端重启恢复会把未完成任务标记为失败。
    }
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  void ask()
}

function clearConversation() {
  if (!window.confirm('清空当前会话界面？历史记录仍会保存在左侧，不会删除。')) return
  stop()
  if (activeSessionId.value) {
    sessionCache[activeSessionId.value] = []
  }
}

function sourceLocation(source: CitationSource): string {
  return source.location_text
}

function providerLabel(turn: AnswerTurn): string {  if (turn.scope === 'GENERAL') return 'DeepSeek 通用知识'
  if (turn.provider === 'DEEPSEEK') return 'DeepSeek 增强'
  if (turn.provider === 'HARNESS') return 'Harness 执行'
  return '千问本地回答'
}

function openCitation(turn: AnswerTurn, number: number) {
  const source = turn.sources.find((item) => item.citation_number === number)
  if (source) {
    selectedCitation.value = source
  } else if (number >= 1 && number <= turn.sources.length) {
    selectedCitation.value = turn.sources[number - 1]
  }
}

function openInLibrary(documentId: string) {
  selectedCitation.value = null
  window.dispatchEvent(new CustomEvent('company-open-document', { detail: documentId }))
  window.dispatchEvent(new CustomEvent('company-switch-page', { detail: 'library' }))
}

function copyAnswer(turn: AnswerTurn) {
  if (!navigator.clipboard || !turn.answer) return
  void navigator.clipboard.writeText(turn.answer)
}

function exportMarkdown(turn: AnswerTurn) {
  const lines = [`# ${turn.question}`, '', turn.answer, '']
  if (turn.sources.length) {
    lines.push('## 引用来源')
    for (const source of turn.sources) {
      lines.push(`- [${source.citation_number}] ${source.document_name} · ${source.location_text}`)
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `answer-${turn.key}.md`
  anchor.click()
  URL.revokeObjectURL(url)
}

async function exportPdf(turn: AnswerTurn) {
  if (!turn.assistantMessageId || turn.pdfExporting) return
  turn.pdfExporting = true
  turn.pdfExportNotice = null
  try {
    const blob = await downloadAnswerPdf(turn.assistantMessageId)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `康师傅知识回答-${turn.key}.pdf`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
    turn.pdfExportNotice = { kind: 'success', message: 'PDF 已生成并开始下载' }
  } catch (reason) {
    turn.pdfExportNotice = { kind: 'error', message: reason instanceof Error ? reason.message : 'PDF 导出失败，请稍后重试' }
  } finally {
    turn.pdfExporting = false
  }
}

function reportAnswer(turn: AnswerTurn) {
  turn.feedbackReasons = ['举报敏感或错误内容']
  turn.feedbackComment = turn.feedbackComment ?? ''
  turn.feedbackNotice = null
  turn.feedbackMode = true
}

function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${Math.round(value)}ms`
}

function latencySummary(turn: AnswerTurn): string {
  const metrics = turn.metrics
  if (!metrics) return ''
  const parts = [
    `检索 ${formatMs(metrics.retrieval_ms ?? null)}`,
    `生成 ${formatMs(metrics.llm_generation_ms ?? null)}`,
    `首字 ${formatMs(metrics.llm_first_token_ms ?? null)}`,
    `总计 ${formatMs(metrics.total_ms ?? null)}`,
  ]
  if (metrics.cache_hit) parts.push('缓存命中')
  return parts.join(' · ')
}

const fallbackQuestions = [
  '公司目前采用什么气泡检测方案？',
  'Go 服务如何部署到 Kubernetes？',
  '最新的休假和考勤制度是什么？',
  '报销流程需要提交哪些材料？',
  '质检报告主要包含哪些指标？',
  '如何申请内网服务器权限？',
]
const suggestionQuestions = computed(() => {
  const configured = currentAssistant.value?.recommended_questions ?? []
  return configured.length ? configured.slice(0, 6) : fallbackQuestions
})

function welcomeCopy(): string {
  const message = currentAssistant.value?.welcome_message
  if (message) return message
  const name = currentAssistant.value?.name || '康师傅公司助手'
  return `你好，我是${name}，可以基于公司内部资料回答你的问题。`
}

async function scrollToBottom(smooth: boolean) {
  await nextTick()
  const pane = scrollPane.value
  if (!pane) return
  const nearBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 160
  if (smooth || nearBottom) {
    pane.scrollTo({ top: pane.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }
}

function autoResize() {
  const el = composerInput.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

function onAdvancedToggle(event: Event) {
  advancedOpen.value = (event.target as HTMLDetailsElement).open
}

function saveDraft() {
  window.localStorage.setItem(DRAFT_KEY, question.value)
}

watch([sessionSearch, showArchived], () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refreshSessions, 250)
})

const DOWN_REASONS = ['答非所问', '内容不准确', '引用不正确', '资料已经过期', '回答不完整', '没有找到已有资料', '回答速度太慢', '缺失知识', '资料不足', '举报敏感或错误内容']

function openFeedbackMode(turn: AnswerTurn) {
  turn.feedbackMode = !turn.feedbackMode
  turn.feedbackNotice = null
  if (turn.feedbackMode) {
    turn.feedbackReasons = []
    turn.feedbackComment = ''
  }
}

async function sendFeedback(turn: AnswerTurn, rating: 'UP' | 'DOWN') {
  const reporting = rating === 'DOWN' && (turn.feedbackReasons ?? []).includes('举报敏感或错误内容')
  if (!turn.assistantMessageId) {
    turn.feedbackNotice = { kind: 'error', message: reporting ? '当前回答尚未保存，暂时无法举报' : '当前回答尚未保存，暂时无法提交反馈' }
    return
  }
  if (turn.feedbackSubmitting) return
  const reasons = rating === 'DOWN' ? (turn.feedbackReasons ?? []) : []
  const comment = rating === 'DOWN' ? (turn.feedbackComment ?? '').trim() : ''
  turn.feedbackSubmitting = true
  turn.feedbackNotice = null
  try {
    await submitFeedback({ messageId: turn.assistantMessageId, rating, reasons, comment })
    turn.feedbackRating = rating
    turn.feedbackMode = false
    turn.feedbackNotice = {
      kind: 'success',
      message: reporting ? '举报已提交，我们会尽快核查' : '反馈已提交，感谢你的帮助',
    }
  } catch (reason) {
    turn.feedbackNotice = {
      kind: 'error',
      message: reason instanceof Error ? reason.message : (reporting ? '举报提交失败，请稍后重试' : '反馈提交失败，请稍后重试'),
    }
  } finally {
    turn.feedbackSubmitting = false
  }
}

function askGeneralKnowledge(turn: AnswerTurn) {
  void regenerate(turn)
}

async function submitMissingKnowledge(turn: AnswerTurn) {
  turn.feedbackReasons = ['缺失知识']
  turn.feedbackComment = turn.feedbackComment ?? ''
  await sendFeedback(turn, 'DOWN')
}

function toggleReason(turn: AnswerTurn, reason: string) {
  if (!turn.feedbackReasons) turn.feedbackReasons = []
  const index = turn.feedbackReasons.indexOf(reason)
  if (index >= 0) turn.feedbackReasons.splice(index, 1)
  else turn.feedbackReasons.push(reason)
}

async function restorePendingApproval() {
  const taskId = window.localStorage.getItem('company-search-pending-harness-task')
  if (!taskId || !activeSessionId.value) return
  try {
    const task = await getHarnessTask(taskId)
    const pending = task.approvals.find((item) => item.status === 'PENDING') ?? null
    if (!pending) {
      window.localStorage.removeItem('company-search-pending-harness-task')
      return
    }
    const turns = activeTurns.value
    const turn = turns.find((item) => item.harnessTaskId === taskId)
    if (turn && !turn.approval) {
      turn.approval = pending as HarnessApproval
      turn.stage = null
      turn.generating = false
    }
  } catch {
    window.localStorage.removeItem('company-search-pending-harness-task')
  }
}

onMounted(() => {
  const draft = window.localStorage.getItem(DRAFT_KEY)
  if (draft) question.value = draft
  void loadAssistants()
  void loadStatus()
  void loadKnowledgeBases()
  void restoreInitialSession().then(() => restorePendingApproval())
})

onBeforeUnmount(() => {
  stop()
  window.clearTimeout(searchTimer)
  saveDraft()
})
</script>

<template>
  <div class="qa-layout">
    <SessionSidebar
      :items="sessions"
      :active-id="activeSessionId"
      :show-archived="showArchived"
      :loading="sessionsLoading"
      @select="selectSession($event)"
      @create="newSession"
      @rename="renameSession"
      @archive="archiveSession"
      @restore="restoreArchivedSession"
      @purge="purgeSession"
      @search="sessionSearch = $event"
      @toggle-archived="showArchived = $event"
    />

    <main class="qa-main">
      <header class="qa-topbar">
        <div class="qa-assistant">
          <span class="qa-avatar">{{ assistantAvatar }}</span>
          <div>
            <strong>{{ currentAssistant?.name || '康师傅公司助手' }}</strong>
            <span>{{ currentAssistant?.description || '公司综合知识助手' }}</span>
          </div>
        </div>
        <label v-if="assistants.length > 1" class="assistant-switch">
          助手
          <select v-model="currentAssistantId">
            <option v-for="item in assistants" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </label>
        <div class="qa-topmeta">
          <span class="qa-chip" :title="'当前检索范围'">{{ scopeLabel }}</span>
          <span class="qa-chip" :class="ollamaReady ? 'is-ready' : 'is-offline'">
            {{ ollamaReady ? '千问已就绪' : '本地模型未就绪' }}
          </span>
          <span class="qa-chip" :class="generalKnowledgeAllowed ? 'is-ready' : ''">{{ generalKnowledgeAllowed ? '可查通用知识' : '仅内部资料' }}</span>
          <span v-if="assistantWelcome?.operations_allowed" class="qa-chip is-ready">可执行运维任务</span>
          <button v-if="ollamaReady" type="button" class="qa-topbutton" :disabled="warming" @click="warmUpModel(true)">{{ warming ? '预热中…' : '预热模型' }}</button>
          <button type="button" class="qa-topbutton" @click="loadStatus">重新检查</button>
        </div>
      </header>

      <p v-if="statusError" class="error">{{ statusError }}</p>
      <p v-if="status && !ollamaReady" class="answer-notice is-warning">
        请先启动 Ollama 并确认已下载模型：<code>ollama pull {{ status.ollama.model }}</code>，然后点击「重新检查」。
      </p>

      <div ref="scrollPane" class="qa-scroll">
        <div v-if="!activeTurns.length && !loadingSession" class="qa-welcome">
          <div class="welcome-avatar">{{ assistantAvatar }}</div>
          <h2>{{ welcomeCopy() }}</h2>
          <p>资料检索范围由所选助手决定；回答会标注来源，点击 [n] 可查看引用原文。</p>
          <div class="welcome-suggestions">
            <button v-for="item in suggestionQuestions" :key="item" type="button" class="suggestion-chip" @click="ask(item)">{{ item }}</button>
          </div>
          <div v-if="knowledgeBases.length" class="welcome-kbs">
            <strong>常用知识库</strong>
            <div>
              <button
                v-for="item in enabledBases"
                :key="item.id"
                type="button"
                :class="{ active: item.id === knowledgeBaseId }"
                @click="knowledgeBaseId = item.id"
              >{{ item.name }}</button>
            </div>
          </div>

          <div v-if="assistantWelcome" class="welcome-capabilities">
            <div class="welcome-cap-block">
              <strong>能做什么</strong>
              <ul v-if="assistantWelcome.capabilities.length">
                <li v-for="item in assistantWelcome.capabilities" :key="item">{{ item }}</li>
              </ul>
              <p v-else class="assistant-hint">基于已授权资料回答并标注引用。</p>
            </div>
            <div class="welcome-cap-block">
              <strong>不能做什么</strong>
              <ul v-if="assistantWelcome.limitations.length">
                <li v-for="item in assistantWelcome.limitations" :key="item">{{ item }}</li>
              </ul>
              <p v-else class="assistant-hint">不访问无权资料，没有依据时不编造结论。</p>
            </div>
            <div class="welcome-cap-block">
              <strong>可访问资料范围</strong>
              <p>{{ assistantWelcome.knowledge_scope }}</p>
              <p v-if="!assistantWelcome.knowledge_scope_configured" class="answer-notice is-warning">
                该助手尚未配置资料范围，暂时无法检索知识库。
              </p>
              <p class="assistant-hint">
                通用知识：{{ assistantWelcome.general_knowledge_allowed ? '允许' : '不允许' }} ·
                运维任务：{{ assistantWelcome.operations_allowed ? '允许' : '不允许' }} ·
                联网：{{ assistantWelcome.internet_enabled ? (assistantWelcome.internet_configured ? '已配置' : '联网服务未配置') : '不允许' }}
              </p>
            </div>
            <div v-if="assistantWelcome.recent_questions.length" class="welcome-cap-block">
              <strong>最近热门问题</strong>
              <div class="welcome-suggestions">
                <button v-for="item in assistantWelcome.recent_questions" :key="item" type="button" class="suggestion-chip" @click="ask(item)">{{ item }}</button>
              </div>
            </div>
          </div>
        </div>

        <div v-for="turn in activeTurns" :key="turn.key" class="qa-turn">
          <div class="user-bubble">
            <span class="user-avatar">我</span>
            <div>
              <p>{{ turn.question }}</p>
              <small v-if="turn.userMessageId">刚刚</small>
            </div>
          </div>

          <article class="answer-card" :class="{ generating: turn.generating, failed: turn.failed }">
            <header class="answer-card-head">
              <div class="assistant-identity">
                <span class="assistant-avatar">康</span>
                <div>
                  <strong>{{ providerLabel(turn) }}</strong>
                  <span class="scope-badge" v-if="turn.scope === 'INTERNAL_LIMITED'">内部资料依据有限</span>
                  <span class="scope-badge warn" v-else-if="turn.scope === 'GENERAL'">不来自公司资料库</span>
                  <span v-if="turn.confidence" class="confidence-badge" :class="`conf-${turn.confidence.tier.toLowerCase()}`">{{ turn.confidence.label }}</span>
                  <span v-if="turn.questionType" class="scope-badge">{{ turn.questionType }}</span>
                  <span class="status-badge" v-if="turn.stopped">已停止</span>
                  <span class="status-badge fail" v-else-if="turn.failed">生成失败</span>
                </div>
              </div>
              <div class="answer-actions" v-if="turn.answer || !turn.generating">
                <button v-if="turn.answer" type="button" title="复制回答" @click="copyAnswer(turn)">复制</button>
                <button v-if="turn.answer" type="button" title="导出 Markdown" @click="exportMarkdown(turn)">导出 MD</button>
                <button v-if="turn.answer" type="button" title="下载 PDF" :disabled="turn.pdfExporting" @click="exportPdf(turn)">{{ turn.pdfExporting ? '生成 PDF…' : '导出 PDF' }}</button>
                <button v-if="turn.answer && !turn.generating" type="button" title="重新生成" @click="regenerate(turn)">重新生成</button>
                <button v-if="turn.answer && !turn.generating" type="button" class="text-danger" title="举报敏感或错误答案" @click="reportAnswer(turn)">举报</button>
              </div>
            </header>

            <p v-if="turn.pdfExportNotice" class="answer-notice" :class="turn.pdfExportNotice.kind === 'success' ? 'is-success' : 'is-warning'">{{ turn.pdfExportNotice.message }}</p>
            <p v-if="turn.feedbackNotice" class="answer-notice" :class="turn.feedbackNotice.kind === 'success' ? 'is-success' : 'is-warning'">{{ turn.feedbackNotice.message }}</p>
            <div v-if="turn.feedbackMode" class="feedback-panel is-prominent">
              <p>{{ (turn.feedbackReasons ?? []).includes('举报敏感或错误内容') ? '举报这个回答' : '请告诉我哪里不够好（可多选）' }}</p>
              <div class="feedback-reasons">
                <label v-for="reason in DOWN_REASONS" :key="reason">
                  <input
                    type="checkbox"
                    :checked="(turn.feedbackReasons ?? []).includes(reason)"
                    @change="toggleReason(turn, reason)"
                  >{{ reason }}
                </label>
              </div>
              <textarea v-model="turn.feedbackComment" rows="3" maxlength="2000" :placeholder="(turn.feedbackReasons ?? []).includes('举报敏感或错误内容') ? '请补充举报原因或问题位置（可选）' : '补充意见（可选）'"></textarea>
              <div class="feedback-actions">
                <button type="button" class="secondary-action" :disabled="turn.feedbackSubmitting" @click="turn.feedbackMode = false">取消</button>
                <button type="button" class="send-answer" :disabled="turn.feedbackSubmitting" @click="sendFeedback(turn, 'DOWN')">{{ turn.feedbackSubmitting ? '提交中…' : ((turn.feedbackReasons ?? []).includes('举报敏感或错误内容') ? '提交举报' : '提交反馈') }}</button>
              </div>
            </div>

            <div v-if="turn.generating" class="answer-stage">
              <span></span>{{ stageText(turn) }}
            </div>
            <div v-if="turn.stage === 'local_generating' && !turn.answer" class="typing-dots"><i></i><i></i><i></i></div>

            <div v-if="turn.answer" class="answer-card-body">
              <MarkdownView :source="turn.answer" @citation="openCitation(turn, $event)" />
            </div>

            <p v-if="turn.errorMessage && !turn.answer" class="answer-notice is-warning">{{ turn.errorMessage }}</p>
            <p v-for="warning in turn.warnings" :key="warning.code" class="answer-notice is-warning">{{ warning.message }}</p>

            <div v-if="turn.citationCheck && !turn.citationCheck.ok" class="citation-check-note">
              <span v-if="turn.citationCheck.invalid_numbers.length">存在无效引用编号：{{ turn.citationCheck.invalid_numbers.join('、') }}</span>
              <span v-if="turn.citationCheck.unsupported_sentences.length">有 {{ turn.citationCheck.unsupported_sentences.length }} 处内容缺少依据，已标记为“推断”。</span>
              <span v-if="turn.citationCheck.unavailable_citations.length">引用 {{ turn.citationCheck.unavailable_citations.join('、') }} 对应的资料当前不可访问。</span>
            </div>

            <div v-if="turn.noAnswer" class="no-answer-panel">
              <p class="no-answer-message">{{ turn.noAnswer.message }}</p>
              <div v-if="turn.noAnswer.recommended_documents.length" class="no-answer-block">
                <strong>推荐相关资料</strong>
                <ul>
                  <li v-for="doc in turn.noAnswer.recommended_documents" :key="doc.id">
                    <button type="button" class="link-button" @click="openInLibrary(doc.id)">{{ doc.name }}</button>
                  </li>
                </ul>
              </div>
              <div v-if="turn.noAnswer.rephrase_suggestions.length" class="no-answer-block">
                <strong>换一种问法</strong>
                <ul><li v-for="(tip, index) in turn.noAnswer.rephrase_suggestions" :key="index">{{ tip }}</li></ul>
              </div>
              <div class="no-answer-actions">
                <button v-if="turn.noAnswer.allow_deepseek && turn.noAnswer.deepseek_configured" type="button" class="secondary-action" @click="askGeneralKnowledge(turn)">使用 DeepSeek 通用知识</button>
                <button type="button" class="secondary-action" @click="submitMissingKnowledge(turn)">提交“缺失知识”反馈</button>
              </div>
            </div>

            <div v-if="turn.suggestions && turn.suggestions.length && !turn.generating" class="follow-up-suggestions">
              <span>你可能还想问：</span>
              <button v-for="item in turn.suggestions" :key="item" type="button" class="suggestion-chip" @click="ask(item)">{{ item }}</button>
            </div>

            <div v-if="turn.stopped && turn.answer" class="stopped-note">回答已被停止，以下是已生成的部分。</div>

            <HarnessTimeline :steps="turn.harnessSteps" />
            <HarnessApprovalCard v-if="turn.approval" :approval="turn.approval" :busy="approvalBusy" @confirm="decideApproval(turn, $event)" @reject="decideApproval(turn, null)" />

            <div v-if="!turn.generating && turn.assistantMessageId && turn.answer" class="feedback-bar">
              <span v-if="turn.feedbackRating" class="feedback-done">{{ turn.feedbackRating === 'UP' ? '已标记有帮助' : '已标记没帮助' }}</span>
              <template v-else>
                <span class="feedback-ask">这个回答有帮助吗？</span>
                <button type="button" class="foot-action like" @click="sendFeedback(turn, 'UP')">有帮助</button>
                <button type="button" class="foot-action dislike" @click="openFeedbackMode(turn)">没帮助</button>
              </template>
            </div>
            <p v-if="turn.metrics?.retrieval_query && turn.metrics.retrieval_query !== turn.question" class="retrieval-query-note">
              实际检索问题：{{ turn.metrics.retrieval_query }}
              <span v-if="turn.metrics.retrieval_queries && turn.metrics.retrieval_queries.length > 1">（多查询：{{ turn.metrics.retrieval_queries.join(' ｜ ') }}）</span>
            </p>
            <footer v-if="turn.answer || turn.sources.length" class="answer-card-foot">
              <span v-if="turn.answer && turn.metrics && latencySummary(turn)" class="metrics-note">{{ latencySummary(turn) }}</span>
              <span v-if="turn.sources.length" class="source-toggle" @click="turn.sourcesVisible = !turn.sourcesVisible">
                {{ turn.sourcesVisible ? '收起引用' : `查看 ${turn.sources.length} 条引用` }}
              </span>
            </footer>
          </article>

          <section v-if="turn.sourcesVisible" class="citation-strip">
            <button
              v-for="source in turn.sources"
              :key="`${source.chunk_id}-${source.citation_number}`"
              type="button"
              class="citation-chip"
              @click="selectedCitation = source"
            >
              <b>[{{ source.citation_number }}]</b>
              <span>{{ source.document_name }}</span>
              <em>{{ source.location_text }}</em>
              <i v-if="source.status !== 'ACTIVE'" :title="source.status === 'DELETED' ? '已删除' : '已停用'">停用</i>
            </button>
          </section>
        </div>

        <div ref="conversationEnd"></div>
      </div>

      <section class="qa-composer">
        <details :open="advancedOpen" class="qa-advanced" @toggle="onAdvancedToggle">
          <summary>高级设置</summary>
          <div class="qa-advanced-body">
            <label class="qa-field"><span>知识库范围</span><select v-model="knowledgeBaseId"><option value="">全部知识库</option><option v-for="item in enabledBases" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          </div>
        </details>

        <form class="composer-form" @submit.prevent="ask()">
          <textarea
            ref="composerInput"
            v-model="question"
            rows="1"
            maxlength="1000"
            placeholder="输入关于公司资料的问题，Enter 发送…"
            @keydown="handleKeydown"
            @input="autoResize; saveDraft()"
          ></textarea>
          <div class="composer-actions">
            <button v-if="activeController" type="button" class="stop-answer" @click="cancelGeneration">停止生成</button>
            <button v-else type="submit" class="send-answer" :disabled="!question.trim()">发送</button>
          </div>
        </form>
        <small class="composer-hint">Enter 发送 · Shift + Enter 换行 · 切换页面后当前输入与生成状态都会保留</small>
      </section>
    </main>

    <ReferenceDrawer :source="selectedCitation" @close="selectedCitation = null" @open-document="openInLibrary" />
  </div>
</template>
