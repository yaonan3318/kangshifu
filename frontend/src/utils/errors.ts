import { ApiError } from '../api/documents'

const STATUS_MESSAGES: Record<number, string> = {
  401: '登录已失效，请重新登录',
  403: '没有操作权限',
  404: '对象不存在或无权查看',
  409: '名称重复或状态冲突',
  422: '输入参数不正确',
  500: '系统内部错误',
}

/** 把接口异常转换成统一的中文提示。 */
export function errorMessage(reason: unknown, fallback = '请求失败'): string {
  if (reason instanceof ApiError) {
    // 功能权限被后端拒绝时给出明确提示，避免被通用 403 文案覆盖。
    if (reason.code === 'PERMISSION_DENIED') return '当前账号没有此功能权限'
    if (reason.status && STATUS_MESSAGES[reason.status]) return STATUS_MESSAGES[reason.status]
    return reason.message || fallback
  }
  if (reason instanceof Error) return reason.message || fallback
  return fallback
}
