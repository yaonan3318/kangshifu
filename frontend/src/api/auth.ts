import type { ApiErrorBody } from '../types/documents'

export interface AuthUser {
  id: string
  username: string
  display_name: string
  department_id: string | null
  enabled: boolean
  is_super_admin: boolean
  last_login_at: string | null
  department_name: string | null
  roles: string[]
  permissions: string[]
}

export interface AuthMe {
  authenticated: boolean
  user: AuthUser | null
}

export class AuthError extends Error {
  constructor(public code: string, message: string) {
    super(message)
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json()
  const body = (await response.json().catch(() => ({}))) as ApiErrorBody
  throw new AuthError(body.error?.code ?? 'AUTH_FAILED', body.error?.message ?? '请求失败')
}

export async function getAuthState(): Promise<AuthMe> {
  const response = await fetch('/api/auth/me')
  return parse<AuthMe>(response)
}

export async function loginRequest(username: string, password: string): Promise<AuthMe> {
  const response = await fetch('/api/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const body = await parse<AuthMe & { user: AuthUser }>(response)
  return { authenticated: body.authenticated, user: body.user }
}

export async function logoutRequest(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST' })
}

export async function listUsers(search?: string): Promise<{ items: AuthUser[]; total: number }> {
  const query = search ? `?search=${encodeURIComponent(search)}` : ''
  const response = await fetch(`/api/users${query}`)
  return parse(response)
}
