import { ref } from 'vue'

/** 后端固定权限码；前端只做展示控制，安全校验始终在后端。 */
export type PermissionCode =
  | 'ANSWER_USE'
  | 'SEARCH_USE'
  | 'DOCUMENT_VIEW'
  | 'DOCUMENT_UPLOAD'
  | 'DOCUMENT_MANAGE'
  | 'KNOWLEDGE_BASE_MANAGE'
  | 'RETRIEVAL_LAB_USE'
  | 'ASSISTANT_MANAGE'
  | 'IDENTITY_MANAGE'
  | 'AUDIT_VIEW'
  | 'STATS_VIEW'
  | 'FEEDBACK_VIEW'
  | 'FEEDBACK_MANAGE'
  | 'FEEDBACK_ASSIGN'
  | 'FEEDBACK_VERIFY'
  | 'FEEDBACK_STATISTICS'
  | 'HARNESS_USE'

const permissionSet = ref<Set<string>>(new Set())

/** 登录或刷新后写入后端返回的有效权限码。 */
export function setPermissions(codes: string[] | null | undefined): void {
  permissionSet.value = new Set(codes ?? [])
}

export function clearPermissions(): void {
  permissionSet.value = new Set()
}

export function hasPermission(code: PermissionCode): boolean {
  return permissionSet.value.has(code)
}

export function hasAnyPermission(codes: PermissionCode[]): boolean {
  return codes.some((code) => permissionSet.value.has(code))
}

export function permissionCodes(): string[] {
  return Array.from(permissionSet.value)
}
