<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createUser, disableUser, enableUser, listRoles, listUsers, resetUserPassword, updateUser,
} from '../../api/identity'
import { getDepartmentTree } from '../../api/identity'
import type { AdminUser, DepartmentNode, RoleRecord } from '../../types/identity'
import { errorMessage } from '../../utils/errors'

const items = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const error = ref('')
const notice = ref('')
const departments = ref<DepartmentNode[]>([])
const roles = ref<RoleRecord[]>([])

const filters = reactive<{ search: string; department_id: string; role_id: string; enabled: string }>({
  search: '', department_id: '', role_id: '', enabled: '',
})

const selectedId = ref('')
const editing = ref(false)
const saving = ref(false)
const passwordTarget = ref<AdminUser | null>(null)
const newPassword = ref('')

const form = reactive({
  username: '',
  display_name: '',
  password: '',
  department_id: '',
  role_ids: [] as string[],
  is_super_admin: false,
  enabled: true,
})

const flatDepartments = computed(() => {
  const out: Array<{ id: string; label: string; enabled: boolean }> = []
  const walk = (nodes: DepartmentNode[], depth: number) => {
    for (const node of nodes) {
      out.push({ id: node.id, label: `${'　'.repeat(depth)}${node.name}`, enabled: node.enabled })
      walk(node.children, depth + 1)
    }
  }
  walk(departments.value, 0)
  return out
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const result = await listUsers({
      search: filters.search || undefined,
      department_id: filters.department_id || undefined,
      role_id: filters.role_id || undefined,
      enabled: filters.enabled === '' ? undefined : filters.enabled === 'true',
      page: page.value,
      page_size: pageSize,
    })
    items.value = result.items
    total.value = result.total
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取用户')
  } finally {
    loading.value = false
  }
}

async function loadReference() {
  try {
    const [tree, roleResult] = await Promise.all([getDepartmentTree(), listRoles()])
    departments.value = tree
    roles.value = roleResult.items
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取部门或角色')
  }
}

function resetForm() {
  selectedId.value = ''
  editing.value = false
  form.username = ''
  form.display_name = ''
  form.password = ''
  form.department_id = ''
  form.role_ids = []
  form.is_super_admin = false
  form.enabled = true
}

function selectUser(user: AdminUser) {
  selectedId.value = user.id
  editing.value = true
  form.username = user.username
  form.display_name = user.display_name
  form.password = ''
  form.department_id = user.department_id ?? ''
  form.role_ids = user.roles.map((role) => role.id)
  form.is_super_admin = user.is_super_admin
  form.enabled = user.enabled
}

function toggleRole(id: string) {
  const index = form.role_ids.indexOf(id)
  if (index >= 0) form.role_ids.splice(index, 1)
  else form.role_ids.push(id)
}

async function save() {
  if (!form.display_name.trim()) { error.value = '请填写显示名称'; return }
  if (!editing.value && form.password.length < 8) { error.value = '初始密码至少 8 位'; return }
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    if (editing.value && selectedId.value) {
      await updateUser(selectedId.value, {
        display_name: form.display_name.trim(),
        department_id: form.department_id || null,
        role_ids: form.role_ids,
        is_super_admin: form.is_super_admin,
        enabled: form.enabled,
      })
      notice.value = '用户已更新'
    } else {
      await createUser({
        username: form.username.trim(),
        display_name: form.display_name.trim(),
        password: form.password,
        department_id: form.department_id || null,
        role_ids: form.role_ids,
        is_super_admin: form.is_super_admin,
        enabled: form.enabled,
      })
      notice.value = '用户已创建'
    }
    resetForm()
    await refresh()
  } catch (reason) {
    error.value = errorMessage(reason, '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(user: AdminUser) {
  const action = user.enabled ? '停用' : '启用'
  if (user.enabled && !window.confirm(`确定停用用户“${user.display_name}”？停用后该用户所有登录会话将立即失效。`)) return
  try {
    if (user.enabled) await disableUser(user.id)
    else await enableUser(user.id)
    notice.value = `用户已${action}`
    await refresh()
  } catch (reason) {
    error.value = errorMessage(reason, `${action}失败`)
  }
}

function startResetPassword(user: AdminUser) {
  passwordTarget.value = user
  newPassword.value = ''
  error.value = ''
}

async function confirmResetPassword() {
  if (!passwordTarget.value) return
  if (newPassword.value.length < 8) { error.value = '新密码至少 8 位'; return }
  if (!window.confirm(`确定重置“${passwordTarget.value.display_name}”的密码？该用户所有登录会话将立即失效。`)) return
  try {
    await resetUserPassword(passwordTarget.value.id, newPassword.value)
    notice.value = '密码已重置，用户需重新登录'
    passwordTarget.value = null
    newPassword.value = ''
  } catch (reason) {
    error.value = errorMessage(reason, '重置密码失败')
  }
}

function changePage(next: number) {
  page.value = next
  void refresh()
}

onMounted(async () => {
  await loadReference()
  await refresh()
})
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">SYSTEM · USERS</p>
      <h1>用户管理</h1>
      <p>维护本地账号、所属部门与角色。停用用户会立即撤销其全部登录会话。</p>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="assistant-hint">{{ notice }}</p>

    <div class="assistant-grid">
      <section class="assistant-panel">
        <div class="section-heading">
          <div><p class="eyebrow">USERS</p><h2>用户列表 <span>{{ total }}</span></h2></div>
          <button type="button" class="primary-action" @click="resetForm">＋ 新建用户</button>
        </div>
        <div class="filter-row">
          <input v-model="filters.search" placeholder="用户名/显示名称" @keyup.enter="page = 1; refresh()">
          <select v-model="filters.department_id" @change="page = 1; refresh()">
            <option value="">全部部门</option>
            <option v-for="dept in flatDepartments" :key="dept.id" :value="dept.id">{{ dept.label }}{{ dept.enabled ? '' : '（停用）' }}</option>
          </select>
          <select v-model="filters.role_id" @change="page = 1; refresh()">
            <option value="">全部角色</option>
            <option v-for="role in roles" :key="role.id" :value="role.id">{{ role.name }}</option>
          </select>
          <select v-model="filters.enabled" @change="page = 1; refresh()">
            <option value="">全部状态</option>
            <option value="true">已启用</option>
            <option value="false">已停用</option>
          </select>
          <button type="button" class="secondary-action" @click="page = 1; refresh()">筛选</button>
        </div>
        <p v-if="loading" class="assistant-hint">正在加载…</p>
        <div v-else class="admin-table-wrap">
          <table class="admin-table">
            <thead><tr><th>用户名</th><th>显示名称</th><th>部门</th><th>角色</th><th>超管</th><th>状态</th><th>最近登录</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="user in items" :key="user.id" :class="{ selected: user.id === selectedId }">
                <td>{{ user.username }}</td>
                <td>{{ user.display_name }}</td>
                <td>{{ user.department_name || '—' }}</td>
                <td>{{ user.roles.map((role) => role.name).join('、') || '—' }}</td>
                <td>{{ user.is_super_admin ? '是' : '否' }}</td>
                <td><span :class="user.enabled ? 'is-active' : 'is-stale'">{{ user.enabled ? '启用' : '停用' }}</span></td>
                <td>{{ user.last_login_at ? new Date(user.last_login_at).toLocaleString('zh-CN', { hour12: false }) : '—' }}</td>
                <td>{{ new Date(user.created_at).toLocaleDateString('zh-CN') }}</td>
                <td class="row-actions">
                  <button type="button" @click="selectUser(user)">编辑</button>
                  <button type="button" @click="toggleEnabled(user)">{{ user.enabled ? '停用' : '启用' }}</button>
                  <button type="button" @click="startResetPassword(user)">重置密码</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <nav v-if="total > pageSize" class="pagination">
          <button :disabled="page === 1" @click="changePage(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
          <button :disabled="page * pageSize >= total" @click="changePage(page + 1)">下一页</button>
        </nav>
      </section>

      <section class="assistant-panel">
        <div class="section-heading"><div><p class="eyebrow">EDITOR</p><h2>{{ editing ? '编辑用户' : '新建用户' }}</h2></div></div>
        <form class="assistant-form" @submit.prevent="save">
          <div class="two-col">
            <label class="form-row">用户名<input v-model="form.username" :disabled="editing" maxlength="255" placeholder="登录名（创建后不可修改）"></label>
            <label class="form-row">显示名称<input v-model="form.display_name" maxlength="255"></label>
          </div>
          <label v-if="!editing" class="form-row">初始密码（至少 8 位）<input v-model="form.password" type="password" autocomplete="new-password"></label>
          <label class="form-row">所属部门
            <select v-model="form.department_id">
              <option value="">未分配</option>
              <option v-for="dept in flatDepartments.filter((d) => d.enabled || d.id === form.department_id)" :key="dept.id" :value="dept.id">{{ dept.label }}</option>
            </select>
          </label>
          <div>
            <p class="assistant-hint" style="margin:0 0 6px">角色（可多选）</p>
            <div class="assistant-checkboxes">
              <label v-for="role in roles" :key="role.id">
                <input type="checkbox" :checked="form.role_ids.includes(role.id)" @change="toggleRole(role.id)">
                {{ role.name }}{{ role.enabled ? '' : '（停用）' }}
              </label>
            </div>
          </div>
          <div class="assistant-checkboxes">
            <label><input v-model="form.is_super_admin" type="checkbox">超级管理员</label>
            <label><input v-model="form.enabled" type="checkbox">启用账号</label>
          </div>
          <div class="form-actions">
            <button type="button" class="secondary-action" @click="resetForm">重置</button>
            <button type="submit" :disabled="saving">{{ saving ? '保存中…' : (editing ? '保存修改' : '创建用户') }}</button>
          </div>
        </form>

        <div v-if="passwordTarget" class="governance-form" style="margin-top:16px">
          <p class="assistant-hint">重置“{{ passwordTarget.display_name }}”的密码</p>
          <label class="form-row">新密码（至少 8 位）<input v-model="newPassword" type="password" autocomplete="new-password"></label>
          <div class="form-actions">
            <button type="button" class="secondary-action" @click="passwordTarget = null">取消</button>
            <button type="button" @click="confirmResetPassword">确认重置</button>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>
