<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createRole, disableRole, enableRole, getPermissionCatalog, getRoleDocuments, listRoles,
  setRoleUsers, updateRole,
} from '../../api/identity'
import { listUsers } from '../../api/identity'
import type {
  AdminUser, PermissionCategory, PermissionItem, RoleDocument, RoleRecord,
} from '../../types/identity'
import { errorMessage } from '../../utils/errors'

const roles = ref<RoleRecord[]>([])
const users = ref<AdminUser[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const selectedId = ref('')
const creating = ref(false)
const saving = ref(false)
const documents = ref<RoleDocument[]>([])
const selectedUserIds = ref<string[]>([])
const showDocuments = ref(false)
const permissionCategories = ref<PermissionCategory[]>([])
const permissionItems = ref<PermissionItem[]>([])

const form = reactive({ name: '', description: '', enabled: true, permissions: [] as string[] })

const permissionGroups = computed(() => permissionCategories.value.map((category) => ({
  ...category,
  items: permissionItems.value.filter((item) => item.category === category.key),
})))

function categoryFullySelected(key: string): boolean {
  const items = permissionItems.value.filter((item) => item.category === key)
  return items.length > 0 && items.every((item) => form.permissions.includes(item.code))
}

function toggleCategory(key: string) {
  const codes = permissionItems.value.filter((item) => item.category === key).map((item) => item.code)
  if (categoryFullySelected(key)) {
    form.permissions = form.permissions.filter((code) => !codes.includes(code))
  } else {
    form.permissions = Array.from(new Set([...form.permissions, ...codes]))
  }
}

function togglePermission(code: string) {
  if (form.permissions.includes(code)) form.permissions = form.permissions.filter((item) => item !== code)
  else form.permissions = [...form.permissions, code]
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [roleResult, userResult] = await Promise.all([listRoles(), listUsers({ page_size: 100 })])
    roles.value = roleResult.items
    users.value = userResult.items
    if (selectedId.value && !roles.value.some((role) => role.id === selectedId.value)) selectedId.value = ''
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取角色')
  } finally {
    loading.value = false
  }
}

function selectRole(role: RoleRecord) {
  creating.value = false
  selectedId.value = role.id
  form.name = role.name
  form.description = role.description ?? ''
  form.enabled = role.enabled
  form.permissions = [...(role.permissions ?? [])]
  showDocuments.value = false
  documents.value = []
  void loadRoleUsers(role)
}

async function loadRoleUsers(role: RoleRecord) {
  try {
    const result = await listUsers({ role_id: role.id, page_size: 100 })
    selectedUserIds.value = result.items.map((user) => user.id)
  } catch {
    selectedUserIds.value = []
  }
}

function startCreate() {
  selectedId.value = ''
  creating.value = true
  form.name = ''
  form.description = ''
  form.enabled = true
  form.permissions = []
  selectedUserIds.value = []
  showDocuments.value = false
  documents.value = []
}

function toggleUser(id: string) {
  const index = selectedUserIds.value.indexOf(id)
  if (index >= 0) selectedUserIds.value.splice(index, 1)
  else selectedUserIds.value.push(id)
}

async function save() {
  if (!form.name.trim()) { error.value = '请填写角色名称'; return }
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const permissions = [...form.permissions]
    if (creating.value) {
      const role = await createRole({ name: form.name.trim(), description: form.description.trim() || null, enabled: form.enabled, permissions })
      selectedId.value = role.id
      creating.value = false
      form.permissions = [...(role.permissions ?? [])]
      notice.value = '角色已创建'
    } else if (selectedId.value) {
      const role = await updateRole(selectedId.value, { name: form.name.trim(), description: form.description.trim() || null, enabled: form.enabled, permissions })
      form.permissions = [...(role.permissions ?? [])]
      notice.value = '角色已更新'
    }
    await refresh()
  } catch (reason) {
    error.value = errorMessage(reason, '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveUsers() {
  if (!selectedId.value) return
  try {
    await setRoleUsers(selectedId.value, selectedUserIds.value)
    notice.value = '角色成员已更新'
    await refresh()
  } catch (reason) {
    error.value = errorMessage(reason, '分配用户失败')
  }
}

async function toggleEnabled(role: RoleRecord) {
  const action = role.enabled ? '停用' : '启用'
  if (role.enabled && !window.confirm(`停用“${role.name}”后，该角色绑定的功能权限会立即失效（成员需刷新后菜单才会更新），历史 ACL 保留。确定停用？`)) return
  try {
    if (role.enabled) await disableRole(role.id)
    else await enableRole(role.id)
    notice.value = `角色已${action}`
    await refresh()
  } catch (reason) {
    error.value = errorMessage(reason, `${action}失败`)
  }
}

async function loadDocuments() {
  if (!selectedId.value) return
  try {
    const result = await getRoleDocuments(selectedId.value)
    documents.value = result.items
    showDocuments.value = true
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取角色文档')
  }
}

async function loadPermissionCatalog() {
  try {
    const data = await getPermissionCatalog()
    permissionCategories.value = data.categories
    permissionItems.value = data.items
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取功能权限目录')
  }
}

onMounted(() => {
  void refresh()
  void loadPermissionCatalog()
})
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">SYSTEM · ROLES</p>
      <h1>角色管理</h1>
      <p>角色用于控制文档访问范围。停用角色不会删除历史授权，重新启用后恢复生效。</p>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="assistant-hint">{{ notice }}</p>

    <div class="role-admin-layout">
      <section class="assistant-panel role-list-panel">
        <div class="section-heading">
          <div><p class="eyebrow">ROLES</p><h2>角色列表</h2></div>
          <button type="button" class="primary-action" @click="startCreate">＋ 新建角色</button>
        </div>
        <p v-if="loading" class="assistant-hint">正在加载…</p>
        <div v-else class="admin-table-wrap">
          <table class="admin-table">
            <colgroup class="role-table-columns">
              <col style="width: 14%"><col style="width: 25%"><col style="width: 7%"><col style="width: 7%">
              <col style="width: 9%"><col style="width: 8%"><col style="width: 12%"><col style="width: 18%">
            </colgroup>
            <thead><tr><th>角色名称</th><th>描述</th><th>用户数</th><th>文档数</th><th>功能权限</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="role in roles" :key="role.id" :class="{ selected: role.id === selectedId }">
                <td>{{ role.name }}</td>
                <td class="role-description" :title="role.description || ''">{{ role.description || '—' }}</td>
                <td>{{ role.user_count }}</td>
                <td>{{ role.document_count }}</td>
                <td>{{ role.permission_count ?? role.permissions?.length ?? 0 }}</td>
                <td><span :class="role.enabled ? 'is-active' : 'is-stale'">{{ role.enabled ? '启用' : '停用' }}</span></td>
                <td>{{ new Date(role.created_at).toLocaleDateString('zh-CN') }}</td>
                <td class="action-cell"><div class="row-actions">
                  <button type="button" @click="selectRole(role)">编辑</button>
                  <button type="button" @click="toggleEnabled(role)">{{ role.enabled ? '停用' : '启用' }}</button>
                </div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div v-if="creating || selectedId" class="role-editor-backdrop" @click.self="selectedId = ''; creating = false">
      <section class="assistant-panel role-editor-panel" role="dialog" aria-modal="true" aria-label="角色编辑">
        <div class="section-heading">
          <div><p class="eyebrow">EDITOR</p><h2>{{ creating ? '新建角色' : '编辑角色' }}</h2></div>
          <button type="button" class="close-button" aria-label="关闭" @click="selectedId = ''; creating = false">×</button>
        </div>
        <form v-if="creating || selectedId" class="assistant-form" @submit.prevent="save">
          <label class="form-row">角色名称<input v-model="form.name" maxlength="255"></label>
          <label class="form-row">描述<textarea v-model="form.description" rows="2" maxlength="500"></textarea></label>
          <label class="admin-check-row"><input v-model="form.enabled" type="checkbox"><span>启用角色</span></label>

          <div class="permission-editor">
            <p class="assistant-hint" style="margin:0 0 8px">功能权限（停用角色后这些权限立即失效）</p>
            <section v-for="group in permissionGroups" :key="group.key" class="permission-group">
              <header>
                <strong>{{ group.label }}</strong>
                <button type="button" class="secondary-action" @click="toggleCategory(group.key)">
                  {{ categoryFullySelected(group.key) ? '取消全选' : '全选本类' }}
                </button>
              </header>
              <div class="permission-options">
                <label v-for="item in group.items" :key="item.code" :title="item.description || ''">
                  <input type="checkbox" :checked="form.permissions.includes(item.code)" @change="togglePermission(item.code)">
                  <span>{{ item.name }}</span>
                </label>
              </div>
            </section>
          </div>

          <div class="form-actions">
            <button type="button" class="secondary-action" @click="selectedId = ''; creating = false">取消</button>
            <button type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </form>

        <div v-if="selectedId && !creating" style="margin-top:18px">
          <p class="assistant-hint" style="margin:0 0 6px">分配用户</p>
          <div class="assistant-checkboxes">
            <label v-for="user in users" :key="user.id">
              <input type="checkbox" :checked="selectedUserIds.includes(user.id)" @change="toggleUser(user.id)">
              {{ user.display_name }}（{{ user.username }}）
            </label>
          </div>
          <div class="form-actions">
            <button type="button" class="secondary-action" @click="loadDocuments">查看可访问文档</button>
            <button type="button" @click="saveUsers">保存成员</button>
          </div>
        </div>

        <div v-if="showDocuments" style="margin-top:14px">
          <p class="assistant-hint" style="margin:0 0 6px">该角色可访问的文档</p>
          <p v-if="!documents.length" class="assistant-hint">暂无通过该角色授权的文档</p>
          <ul v-else class="governance-list">
            <li v-for="doc in documents" :key="doc.document_id">
              <div><strong>{{ doc.document_name }}</strong><small>{{ doc.visibility }} · {{ doc.permission }}</small></div>
            </li>
          </ul>
        </div>
      </section>
      </div>
    </div>
  </main>
</template>
