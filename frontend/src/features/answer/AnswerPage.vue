<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { getAnswerStatus, streamAnswer } from '../../api/answer'
import type { AnswerMessage, AnswerSource, AnswerStatus } from '../../types/answer'

const question = ref('')
const useDeepseek = ref(false)
const status = ref<AnswerStatus | null>(null)
const statusError = ref('')
const messages = ref<AnswerMessage[]>([])
const activeController = ref<AbortController | null>(null)
const conversationEnd = ref<HTMLElement | null>(null)

const stageLabels = {
  retrieving: '正在检索公司资料…',
  local_generating: '千问正在根据资料生成答案…',
  deepseek_enhancing: 'DeepSeek 正在检查并合并答案…',
}

async function loadStatus() {
  try {
    status.value = await getAnswerStatus()
    statusError.value = ''
  } catch (reason) {
    statusError.value = reason instanceof ApiError ? reason.message : '无法检查本地模型状态'
  }
}

async function ask() {
  const value = question.value.trim()
  if (!value || activeController.value) return
  const history = messages.value.filter((item) => item.complete && item.answer).slice(-6).map((item) => ({ question: item.question, answer: item.answer }))
  const message = reactive<AnswerMessage>({
    id: crypto.randomUUID(), question: value, answer: '', sources: [], warnings: [],
    provider: 'LOCAL', scope: null, stage: 'retrieving', complete: false,
  })
  messages.value.push(message)
  question.value = ''
  const controller = new AbortController()
  activeController.value = controller
  await scrollToEnd()
  try {
    await streamAnswer({ question: value, useDeepseek: useDeepseek.value, history }, controller.signal, (event) => {
      if (event.type === 'stage') message.stage = event.stage ?? null
      if (event.type === 'sources') message.sources = event.sources ?? []
      if (event.type === 'replace') { message.answer = ''; message.provider = event.provider ?? 'DEEPSEEK' }
      if (event.type === 'delta') { message.answer += event.text ?? ''; message.provider = event.provider ?? message.provider }
      if (event.type === 'warning' && event.warning) message.warnings.push(event.warning)
      if (event.type === 'done') { message.scope = event.scope ?? null; message.provider = event.provider ?? message.provider; message.stage = null; message.complete = true }
      if (event.type === 'error' && event.error) { message.warnings.push(event.error); message.stage = null; message.complete = true }
      void scrollToEnd()
    })
    if (!message.complete) { message.complete = true; message.stage = null }
  } catch (reason) {
    if (!controller.signal.aborted) {
      message.warnings.push({ code: 'CONNECTION_FAILED', message: reason instanceof Error ? reason.message : '问答连接中断' })
    }
    message.complete = true
    message.stage = null
  } finally {
    activeController.value = null
  }
}

function stop() {
  activeController.value?.abort()
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  void ask()
}

function clearConversation() {
  stop()
  messages.value = []
}

async function scrollToEnd() {
  await nextTick()
  conversationEnd.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
}

function sourceLocation(source: AnswerSource): string {
  if (source.page_start) return `第 ${source.page_start}${source.page_end && source.page_end !== source.page_start ? `–${source.page_end}` : ''} 页`
  if (source.slide_number) return `第 ${source.slide_number} 张幻灯片`
  if (source.sheet_name) return `${source.sheet_name}${source.row_start ? ` · 第 ${source.row_start}${source.row_end && source.row_end !== source.row_start ? `–${source.row_end}` : ''} 行` : ''}`
  return `片段 ${source.sequence_number}`
}

function providerLabel(message: AnswerMessage): string {
  if (message.scope === 'GENERAL') return 'DeepSeek 通用知识'
  return message.provider === 'DEEPSEEK' ? 'DeepSeek 增强' : '千问本地回答'
}

onMounted(loadStatus)
onBeforeUnmount(stop)
</script>

<template>
  <main class="app-shell answer-shell">
    <header class="hero answer-hero">
      <p class="eyebrow">KNOWLEDGE ASSISTANT · LOCAL FIRST</p>
      <h1>公司知识问答</h1>
      <p>先检索内部资料，再由本机千问生成带出处的答案；只有你主动打开开关时才尝试使用 DeepSeek。</p>
    </header>

    <section class="answer-status" aria-label="模型状态">
      <span :class="status?.ollama.reachable && status?.ollama.installed ? 'is-ready' : 'is-offline'">
        {{ status?.ollama.reachable && status?.ollama.installed ? `${status.ollama.model} 已就绪` : '本地模型未就绪' }}
      </span>
      <span>DeepSeek {{ status?.deepseek_configured ? '已配置' : '未配置' }}</span>
      <button type="button" @click="loadStatus">重新检查</button>
      <button v-if="messages.length" type="button" @click="clearConversation">清空会话</button>
    </section>
    <p v-if="statusError" class="error">{{ statusError }}</p>
    <p v-if="status && (!status.ollama.reachable || !status.ollama.installed)" class="answer-notice is-warning">
      请先启动 Ollama 并确认已下载：<code>ollama pull {{ status.ollama.model }}</code>
    </p>

    <section class="conversation" aria-live="polite">
      <div v-if="!messages.length" class="answer-welcome">
        <strong>可以从一个具体问题开始</strong>
        <p>例如：“公司目前采用什么气泡检测方案？”或“Go 服务如何部署到 K8s？”</p>
      </div>
      <article v-for="message in messages" :key="message.id" class="answer-turn">
        <div class="user-message"><span>你</span><p>{{ message.question }}</p></div>
        <div class="assistant-message">
          <header><span>{{ providerLabel(message) }}</span><span v-if="message.scope === 'INTERNAL_LIMITED'" class="scope-warning">内部资料依据有限</span><span v-if="message.scope === 'GENERAL'" class="scope-warning">不来自公司资料库</span></header>
          <p v-if="message.answer" class="answer-text">{{ message.answer }}</p>
          <p v-if="message.stage" class="answer-stage"><span></span>{{ stageLabels[message.stage] }}</p>
          <p v-for="warning in message.warnings" :key="warning.code" class="answer-notice is-warning">{{ warning.message }}</p>
          <details v-if="message.sources.length" class="answer-sources">
            <summary>查看 {{ message.sources.length }} 条引用资料</summary>
            <ol>
              <li v-for="source in message.sources" :key="source.chunk_id">
                <details><summary><b>[{{ source.citation_number }}] {{ source.document_name }}</b><span>{{ sourceLocation(source) }}</span></summary><pre>{{ source.content }}</pre></details>
              </li>
            </ol>
          </details>
        </div>
      </article>
      <div ref="conversationEnd"></div>
    </section>

    <section class="answer-composer">
      <label class="deepseek-toggle"><input v-model="useDeepseek" type="checkbox"><span></span><b>使用 DeepSeek 增强</b></label>
      <p v-if="useDeepseek" class="privacy-hint">
        开启后，本次问题、检索到的内部资料片段和本地初稿将发送给 DeepSeek。
        <strong v-if="status && !status.deepseek_configured">尚未配置 API Key，本次仍将使用千问本地回答。</strong>
      </p>
      <form @submit.prevent="ask">
        <textarea v-model="question" rows="3" maxlength="1000" placeholder="输入关于公司资料的问题…" @keydown="handleKeydown"></textarea>
        <button v-if="activeController" type="button" class="stop-answer" @click="stop">停止</button>
        <button v-else type="submit" :disabled="!question.trim()">发送</button>
      </form>
      <small>Enter 发送 · Shift + Enter 换行 · 当前对话不会永久保存</small>
    </section>
  </main>
</template>
