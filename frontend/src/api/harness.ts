import { ApiError } from './documents'
import type { HarnessStatus, HarnessTaskSnapshot } from '../types/harness'
import type { HarnessApproval } from '../types/answer'
import type { AnswerEvent } from '../types/answer'
import { consumeAnswerResponse } from './answer'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = await response.json().catch(() => ({}))
  throw new ApiError(body.error?.code ?? 'HARNESS_FAILED', body.error?.message ?? 'Harness 请求失败')
}

export function getHarnessStatus(): Promise<HarnessStatus> {
  return fetch('/api/harness/status').then(parse<HarnessStatus>)
}

export function getNamespaces(context: string): Promise<string[]> {
  return fetch(`/api/harness/namespaces?context=${encodeURIComponent(context)}`).then(parse<string[]>)
}

export function getHarnessTask(id: string): Promise<HarnessTaskSnapshot> {
  return fetch(`/api/harness/tasks/${id}`).then(parse<HarnessTaskSnapshot>)
}

export function confirmApproval(id: string, confirmationContext: string): Promise<HarnessApproval> {
  return fetch(`/api/harness/approvals/${id}/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmation_context: confirmationContext }) }).then(parse<HarnessApproval>)
}

export function rejectApproval(id: string, reason = ''): Promise<HarnessApproval> {
  return fetch(`/api/harness/approvals/${id}/reject`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: reason || null }) }).then(parse<HarnessApproval>)
}

export async function resumeHarness(taskId: string, useDeepseek: boolean, onEvent: (event: AnswerEvent) => void): Promise<void> {
  const response = await fetch(`/api/harness/tasks/${taskId}/resume?use_deepseek=${useDeepseek}`, { method: 'POST', headers: { Accept: 'text/event-stream' } })
  await consumeAnswerResponse(response, onEvent)
}
