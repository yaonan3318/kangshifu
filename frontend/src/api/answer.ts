import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { AnswerEvent, AnswerJob, AnswerStatus, AnswerTurn } from '../types/answer'

export async function getAnswerStatus(): Promise<AnswerStatus> {
  const response = await fetch('/api/answer/status')
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'STATUS_FAILED', body.error?.message ?? '无法读取问答服务状态')
}

export async function warmUpAnswer(): Promise<{ warmed: boolean; message: string }> {
  const response = await fetch('/api/answer/warmup', { method: 'POST' })
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'WARMUP_FAILED', body.error?.message ?? '模型预热失败')
}

export interface StreamAnswerInput {
  question: string
  sessionId?: string
  assistantId?: string
  regenerateMessageId?: string
  knowledgeBaseId?: string
  useDeepseek: boolean
  history: Pick<AnswerTurn, 'question' | 'answer'>[]
  useHarness: boolean
  k8sContext?: string
  k8sNamespace?: string
  deploymentYaml?: string
  // P2-5：幂等请求 ID，防止重复提交创建多个生成任务。
  requestId?: string
}

export interface StreamAnswerOutcome {
  sessionId: string | null
  messageId: string | null
  jobId: string | null
}

export async function streamAnswer(
  input: StreamAnswerInput,
  signal: AbortSignal,
  onEvent: (event: AnswerEvent) => void,
  onStarted?: (outcome: StreamAnswerOutcome) => void,
): Promise<StreamAnswerOutcome> {
  const response = await fetch('/api/answer/stream', {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      question: input.question,
      session_id: input.sessionId || null,
      assistant_id: input.assistantId || null,
      regenerate_message_id: input.regenerateMessageId || null,
      knowledge_base_id: input.knowledgeBaseId || null,
      use_deepseek: input.useDeepseek,
      use_harness: input.useHarness,
      k8s_context: input.k8sContext || null,
      k8s_namespace: input.k8sNamespace || null,
      deployment_yaml: input.deploymentYaml || null,
      history: input.history,
      request_id: input.requestId || null,
    }),
  })
  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody
    throw new ApiError(body.error?.code ?? 'ANSWER_FAILED', body.error?.message ?? '无法开始问答')
  }
  const outcome: StreamAnswerOutcome = {
    sessionId: response.headers.get('X-Chat-Session-Id'),
    messageId: response.headers.get('X-Chat-Message-Id'),
    jobId: response.headers.get('X-Answer-Job-Id'),
  }
  onStarted?.(outcome)
  await consumeAnswerResponse(response, onEvent)
  return outcome
}

export async function getAnswerJob(jobId: string): Promise<AnswerJob> {
  const response = await fetch(`/api/answer/jobs/${jobId}`)
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'JOB_FAILED', body.error?.message ?? '无法读取生成任务')
}

export async function cancelAnswerJob(jobId: string): Promise<AnswerJob> {
  const response = await fetch(`/api/answer/jobs/${jobId}/cancel`, { method: 'POST' })
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'JOB_FAILED', body.error?.message ?? '无法取消生成任务')
}

export async function getActiveAnswerJob(sessionId: string): Promise<AnswerJob | null> {
  const response = await fetch(`/api/answer/sessions/${sessionId}/active-job`)
  if (response.ok) return response.json()
  if (response.status === 404) return null
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'JOB_FAILED', body.error?.message ?? '无法读取生成任务')
}

export async function resumeAnswerJob(
  jobId: string,
  cursor: number,
  signal: AbortSignal,
  onEvent: (event: AnswerEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/answer/jobs/${jobId}/stream`, {
    method: 'GET', signal,
    headers: { Accept: 'text/event-stream', 'Last-Event-ID': String(cursor) },
  })
  await consumeAnswerResponse(response, onEvent)
}

export async function consumeAnswerResponse(response: Response, onEvent: (event: AnswerEvent) => void): Promise<void> {
  if (!response.ok || !response.body) throw new Error('Harness 流式连接失败')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) dispatchBlock(block, onEvent)
    if (done) break
  }
  if (buffer.trim()) dispatchBlock(buffer, onEvent)
}

function dispatchBlock(block: string, onEvent: (event: AnswerEvent) => void): void {
  const data = block.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
  if (!data) return
  onEvent(JSON.parse(data) as AnswerEvent)
}
