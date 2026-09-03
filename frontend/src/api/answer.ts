import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type { AnswerEvent, AnswerMessage, AnswerStatus } from '../types/answer'

export async function getAnswerStatus(): Promise<AnswerStatus> {
  const response = await fetch('/api/answer/status')
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'STATUS_FAILED', body.error?.message ?? '无法读取问答服务状态')
}

export interface StreamAnswerInput {
  question: string
  useDeepseek: boolean
  history: Pick<AnswerMessage, 'question' | 'answer'>[]
}

export async function streamAnswer(
  input: StreamAnswerInput,
  signal: AbortSignal,
  onEvent: (event: AnswerEvent) => void,
): Promise<void> {
  const response = await fetch('/api/answer/stream', {
    method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      question: input.question,
      use_deepseek: input.useDeepseek,
      history: input.history,
    }),
  })
  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody
    throw new ApiError(body.error?.code ?? 'ANSWER_FAILED', body.error?.message ?? '无法开始问答')
  }

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
