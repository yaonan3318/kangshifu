export interface RoleBrief {
  id: string
  name: string
}

export interface AdminUser {
  id: string
  username: string
  display_name: string
  department_id: string | null
  department_name: string | null
  roles: RoleBrief[]
  is_super_admin: boolean
  enabled: boolean
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface UserListResponse {
  items: AdminUser[]
  page: number
  page_size: number
  total: number
}

export interface DepartmentRecord {
  id: string
  name: string
  parent_id: string | null
  enabled: boolean
  created_at: string
  updated_at: string
  user_count: number
}

export interface DepartmentNode extends DepartmentRecord {
  children: DepartmentNode[]
}

export interface RoleRecord {
  id: string
  name: string
  description: string | null
  enabled: boolean
  created_at: string
  updated_at: string
  user_count: number
  document_count: number
  permissions: string[]
  permission_count: number
}

export interface PermissionItem {
  code: string
  name: string
  description: string | null
  category: string
  sort_order: number
}

export interface PermissionCategory {
  key: string
  label: string
}

export interface PermissionCatalog {
  categories: PermissionCategory[]
  items: PermissionItem[]
}

export interface RoleListResponse {
  items: RoleRecord[]
  page: number
  page_size: number
  total: number
}

export interface RoleDocument {
  document_id: string
  document_name: string
  visibility: string
  permission: string
}
