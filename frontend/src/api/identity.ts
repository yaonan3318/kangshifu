import { ApiError } from './documents'
import type { ApiErrorBody } from '../types/documents'
import type {
  AdminUser, DepartmentNode, DepartmentRecord, RoleDocument, RoleListResponse, RoleRecord, UserListResponse,
} from '../types/identity'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.status === 204 ? (undefined as T) : response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new ApiError(body.error?.code ?? 'REQUEST_FAILED', body.error?.message ?? '请求失败', body.error?.details, response.status)
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

// ---------------------------------------------------------------- 用户

export interface UserQuery {
  search?: string
  department_id?: string
  role_id?: string
  enabled?: boolean
  page?: number
  page_size?: number
}

export async function listUsers(query: UserQuery = {}): Promise<UserListResponse> {
  const params = new URLSearchParams()
  if (query.search) params.set('search', query.search)
  if (query.department_id) params.set('department_id', query.department_id)
  if (query.role_id) params.set('role_id', query.role_id)
  if (query.enabled !== undefined) params.set('enabled', String(query.enabled))
  params.set('page', String(query.page ?? 1))
  params.set('page_size', String(query.page_size ?? 20))
  return parse(await fetch(`/api/users?${params}`))
}

export interface UserInput {
  username?: string
  display_name?: string
  password?: string
  department_id?: string | null
  role_ids?: string[]
  is_super_admin?: boolean
  enabled?: boolean
}

export async function createUser(body: UserInput): Promise<AdminUser> {
  return parse(await fetch('/api/users', json('POST', body)))
}

export async function updateUser(id: string, body: UserInput): Promise<AdminUser> {
  return parse(await fetch(`/api/users/${id}`, json('PATCH', body)))
}

export async function enableUser(id: string): Promise<AdminUser> {
  return parse(await fetch(`/api/users/${id}/enable`, { method: 'POST' }))
}

export async function disableUser(id: string): Promise<AdminUser> {
  return parse(await fetch(`/api/users/${id}/disable`, { method: 'POST' }))
}

export async function resetUserPassword(id: string, newPassword: string): Promise<{ ok: boolean }> {
  return parse(await fetch(`/api/users/${id}/reset-password`, json('POST', { new_password: newPassword })))
}

// ---------------------------------------------------------------- 部门

export async function getDepartmentTree(): Promise<DepartmentNode[]> {
  return parse(await fetch('/api/departments/tree'))
}

export async function getDepartment(id: string): Promise<DepartmentRecord> {
  return parse(await fetch(`/api/departments/${id}`))
}

export async function createDepartment(body: { name: string; parent_id?: string | null; enabled?: boolean }): Promise<DepartmentRecord> {
  return parse(await fetch('/api/departments', json('POST', body)))
}

export async function updateDepartment(id: string, body: { name?: string; parent_id?: string | null; enabled?: boolean }): Promise<DepartmentRecord> {
  return parse(await fetch(`/api/departments/${id}`, json('PATCH', body)))
}

export async function enableDepartment(id: string): Promise<DepartmentRecord> {
  return parse(await fetch(`/api/departments/${id}/enable`, { method: 'POST' }))
}

export async function disableDepartment(id: string): Promise<DepartmentRecord> {
  return parse(await fetch(`/api/departments/${id}/disable`, { method: 'POST' }))
}

// ---------------------------------------------------------------- 角色

export async function listRoles(page = 1, pageSize = 100): Promise<RoleListResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return parse(await fetch(`/api/roles?${params}`))
}

export async function createRole(body: { name: string; description?: string | null; enabled?: boolean }): Promise<RoleRecord> {
  return parse(await fetch('/api/roles', json('POST', body)))
}

export async function updateRole(id: string, body: { name?: string; description?: string | null; enabled?: boolean }): Promise<RoleRecord> {
  return parse(await fetch(`/api/roles/${id}`, json('PATCH', body)))
}

export async function enableRole(id: string): Promise<RoleRecord> {
  return parse(await fetch(`/api/roles/${id}/enable`, { method: 'POST' }))
}

export async function disableRole(id: string): Promise<RoleRecord> {
  return parse(await fetch(`/api/roles/${id}/disable`, { method: 'POST' }))
}

export async function setRoleUsers(id: string, userIds: string[]): Promise<RoleRecord> {
  return parse(await fetch(`/api/roles/${id}/users`, json('PUT', { user_ids: userIds })))
}

export async function getRoleDocuments(id: string): Promise<{ items: RoleDocument[] }> {
  return parse(await fetch(`/api/roles/${id}/documents`))
}
