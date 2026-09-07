export interface HarnessStatus {
  enabled: boolean
  kubectl_available: boolean
  contexts: string[]
  max_steps: number
  timeout_seconds: number
}

export interface HarnessTaskSnapshot {
  id: string; question: string; context: string; namespace: string
  status: 'RUNNING' | 'AWAITING_APPROVAL' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
  current_step: number; max_steps: number; final_answer: string | null
  error_code: string | null; error_message: string | null
  steps: Array<{ sequence_number: number; status: string; tool_name: string | null; reason: string | null; result: Record<string, unknown> | null }>
  approvals: Array<import('./answer').HarnessApproval & { status: string }>
}
