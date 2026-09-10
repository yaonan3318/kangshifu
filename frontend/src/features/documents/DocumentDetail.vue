<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { listChunks } from '../../api/chunks'
import {
  ApiError, getDocumentAcl, listDocumentVersions, reprocessDocument, setDocumentAccess,
  setDocumentExternalPolicy, updateDocument,
} from '../../api/documents'
import type { AclEntry, AclItem } from '../../api/documents'
import { getDepartmentTree, listRoles, listUsers } from '../../api/identity'
import type { AdminUser, DepartmentNode, RoleRecord } from '../../types/identity'
import type { AuthUser } from '../../api/auth'
import type { DocumentChunk, DocumentRecord } from '../../types/documents'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
import { errorMessage } from '../../utils/errors'
import ChunkEditor from './ChunkEditor.vue'

const props = defineProps<{ document: DocumentRecord; knowledgeBases: KnowledgeBaseRecord[] }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const currentUser = inject<Ref<AuthUser | null>>('currentUser')
const isSuper = computed(() => Boolean(currentUser?.value?.is_super_admin))

const chunks = ref<DocumentChunk[]>([])
const versions = ref<DocumentRecord[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const tab = ref<'overview' | 'chunks' | 'versions' | 'access'>('overview')
const tags = ref(props.document.tags.join(','))
const targetBase = ref(props.document.knowledge_base_id)
const pageSize = 10
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const acl = ref<AclItem[]>([])
const aclLoaded = ref(false)
const aclError = ref('')
const visibility = ref(props.document.visibility)
const newEntry = ref<{ subject_type: AclEntry['subject_type']; subject_id: string; permission: AclEntry['permission'] }>({
  subject_type: 'DEPARTMENT', subject_id: '', permission: 'READ',
})
const departments = ref<DepartmentNode[]>([])
const roles = ref<RoleRecord[]>([])
const users = ref<AdminUser[]>([])
const sensitivity = ref(props.document.sensitivity_level || 'INTERNAL')
const externalAllowed = ref(props.document.external_llm_allowed)

const VISIBILITY_LABELS: Record<string, string> = {
  COMPANY: '全公司可见',
  PRIVATE: '仅自己可见',
  DEPARTMENT: '指定部门可见',
  ROLE: '指定角色可见',
  USER: '指定用户可见',
}
const SENSITIVITY_LABELS: Record<string, string> = {
  PUBLIC: '公开', INTERNAL: '内部', CONFIDENTIAL: '机密', RESTRICTED: '绝密',
}

const flatDepartments = computed(() => {
  const out: Array<{ id: string; label: string }> = []
  const walk = (nodes: DepartmentNode[], depth: number) => {
    for (const node of nodes) {
      out.push({ id: node.id, label: `${'　'.repeat(depth)}${node.name}${node.enabled ? '' : '（停用）'}` })
      walk(node.children, depth + 1)
    }
  }
  walk(departments.value, 0)
  return out
})

const subjectOptions = computed(() => {
  if (newEntry.value.subject_type === 'DEPARTMENT') return flatDepartments.value
  if (newEntry.value.subject_type === 'ROLE') return roles.value.filter((role) => role.enabled).map((role) => ({ id: role.id, label: role.name }))
  return users.value.filter((user) => user.enabled).map((user) => ({ id: user.id, label: `${user.display_name}（${user.username}）` }))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [content, history] = await Promise.all([listChunks(props.document.id, page.value, pageSize), listDocumentVersions(props.document.id)])
    chunks.value = content.items
    total.value = content.total
    versions.value = history
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取文档详情')
  } finally {
    loading.value = false
  }
}

async function saveOverview() {
  try {
    await updateDocument(props.document.id, { knowledge_base_id: targetBase.value, tags: tags.value.split(',').map((x) => x.trim()).filter(Boolean) })
    emit('changed')
  } catch (reason) {
    error.value = errorMessage(reason, '保存失败')
  }
}

async function reprocess() {
  try {
    await reprocessDocument(props.document.id)
    emit('changed')
    emit('close')
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === 'MANUAL_CHUNKS_WOULD_BE_LOST' && window.confirm(`${reason.message}，确定继续吗？`)) {
      await fetch(`/api/documents/${props.document.id}/reprocess?confirm_overwrite=true`, { method: 'POST' })
      emit('changed')
      emit('close')
    } else {
      error.value = errorMessage(reason, '重新处理失败')
    }
  }
}

async function loadAcl() {
  aclError.value = ''
  try {
    const result = await getDocumentAcl(props.document.id)
    acl.value = result.items
    aclLoaded.value = true
  } catch (reason) {
    aclLoaded.value = false
    aclError.value = errorMessage(reason, '无法读取访问权限')
  }
}

async function loadAccessReferences() {
  try {
    const [tree, roleResult, userResult] = await Promise.all([
      getDepartmentTree(), listRoles(), listUsers({ page_size: 100 }),
    ])
    departments.value = tree
    roles.value = roleResult.items
    users.value = userResult.items
  } catch {
    // 引用数据加载失败不阻塞 ACL 读取。
  }
}

function openAccessTab() {
  tab.value = 'access'
  if (!aclLoaded.value) {
    void loadAccessReferences()
    void loadAcl()
  }
}

function addAclEntry() {
  if (!newEntry.value.subject_id) { aclError.value = '请选择授权对象'; return }
  const exists = acl.value.find((item) => item.subject_type === newEntry.value.subject_type && item.subject_id === newEntry.value.subject_id)
  if (exists) {
    exists.permission = newEntry.value.permission
  } else {
    acl.value.push({
      id: `new-${Date.now()}`,
      subject_type: newEntry.value.subject_type,
      subject_id: newEntry.value.subject_id,
      permission: newEntry.value.permission,
      subject_name: subjectOptions.value.find((option) => option.id === newEntry.value.subject_id)?.label ?? null,
    })
  }
  newEntry.value.subject_id = ''
}

function removeAclEntry(item: AclItem) {
  acl.value = acl.value.filter((entry) => entry.id !== item.id)
}

async function saveAccess() {
  aclError.value = ''
  notice.value = ''
  const grantingManage = acl.value.some((item) => item.permission === 'MANAGE')
  if (visibility.value === 'COMPANY' && !window.confirm('将资料设为“全公司可见”后，所有登录用户都可以检索和问答。确定继续？')) return
  if (grantingManage && !window.confirm('本次将授予部分对象 MANAGE 权限，被授权者可以修改该资料。确定继续？')) return
  try {
    await setDocumentAccess(props.document.id, {
      visibility: visibility.value,
      acl: acl.value.map((item) => ({ subject_type: item.subject_type, subject_id: item.subject_id, permission: item.permission })),
    })
    notice.value = '访问权限已保存'
    await loadAcl()
    emit('changed')
  } catch (reason) {
    aclError.value = errorMessage(reason, '保存访问权限失败')
  }
}

async function saveExternalPolicy() {
  aclError.value = ''
  notice.value = ''
  try {
    await setDocumentExternalPolicy(props.document.id, {
      sensitivity_level: sensitivity.value,
      external_llm_allowed: externalAllowed.value,
    })
    notice.value = '外部模型策略已保存'
    emit('changed')
  } catch (reason) {
    aclError.value = errorMessage(reason, '保存外部模型策略失败')
  }
}

watch(() => props.document.id, () => {
  page.value = 1
  tab.value = 'overview'
  aclLoaded.value = false
  acl.value = []
  visibility.value = props.document.visibility
  sensitivity.value = props.document.sensitivity_level || 'INTERNAL'
  externalAllowed.value = props.document.external_llm_allowed
  tags.value = props.document.tags.join(',')
  targetBase.value = props.document.knowledge_base_id
  load()
}, { immediate: true })
watch(page, load)
</script>

<template>
  <div class="detail-backdrop" @click.self="emit('close')">
    <section class="detail-panel" role="dialog" aria-modal="true">
      <header>
        <div><p class="eyebrow">DOCUMENT</p><h2>{{ document.original_name }}</h2></div>
        <button class="close-button" @click="emit('close')">×</button>
      </header>
      <nav class="detail-tabs">
        <button :class="{ active: tab === 'overview' }" @click="tab = 'overview'">基本信息</button>
        <button :class="{ active: tab === 'chunks' }" @click="tab = 'chunks'">片段 {{ total }}</button>
        <button :class="{ active: tab === 'versions' }" @click="tab = 'versions'">版本历史</button>
        <button :class="{ active: tab === 'access' }" @click="openAccessTab">访问权限</button>
      </nav>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="notice" class="assistant-hint">{{ notice }}</p>

      <section v-if="tab === 'overview'" class="detail-section">
        <dl>
          <div><dt>状态</dt><dd>{{ document.status }}</dd></div>
          <div><dt>版本</dt><dd>v{{ document.version_number }}</dd></div>
          <div><dt>相对路径</dt><dd>{{ document.relative_path || '—' }}</dd></div>
          <div><dt>检索状态</dt><dd>{{ document.enabled ? '启用' : '停用' }}</dd></div>
        </dl>
        <div class="governance-form">
          <label>知识库<select v-model="targetBase"><option v-for="item in knowledgeBases.filter((x) => x.enabled)" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          <label>标签<input v-model="tags" placeholder="使用逗号分隔"></label>
          <button @click="saveOverview">保存资料设置</button>
          <button @click="reprocess">重新处理</button>
        </div>
      </section>

      <section v-else-if="tab === 'chunks'">
        <p v-if="loading" class="empty">正在读取片段…</p>
        <ol v-else class="chunk-list"><ChunkEditor v-for="chunk in chunks" :key="chunk.id" :chunk="chunk" @changed="load" /></ol>
        <nav v-if="pages > 1" class="pagination"><button :disabled="page === 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page === pages" @click="page++">下一页</button></nav>
      </section>

      <section v-else-if="tab === 'versions'">
        <ul class="governance-list"><li v-for="item in versions" :key="item.id"><div><strong>v{{ item.version_number }} · {{ item.original_name }}</strong><small>{{ item.status }} · {{ item.enabled ? '启用' : '停用' }}</small></div></li></ul>
      </section>

      <section v-else class="detail-section">
        <p v-if="aclError" class="error">{{ aclError }}</p>
        <template v-if="aclLoaded">
          <div class="governance-form">
            <label>可见范围
              <select v-model="visibility">
                <option v-for="(label, key) in VISIBILITY_LABELS" :key="key" :value="key">{{ label }}</option>
              </select>
            </label>
          </div>

          <div v-if="visibility === 'DEPARTMENT' || visibility === 'ROLE' || visibility === 'USER'">
            <p class="assistant-hint" style="margin:12px 0 6px">授权对象（READ 可查看检索，MANAGE 可管理资料）</p>
            <ul class="acl-list">
              <li v-for="item in acl" :key="item.id">
                <span class="acl-type">{{ { DEPARTMENT: '部门', ROLE: '角色', USER: '用户' }[item.subject_type] }}</span>
                <span class="acl-name">{{ item.subject_name || item.subject_id }}</span>
                <select v-model="item.permission"><option value="READ">可查看</option><option value="MANAGE">可管理</option></select>
                <button type="button" class="text-danger" @click="removeAclEntry(item)">删除授权</button>
              </li>
            </ul>
            <div class="acl-add">
              <select v-model="newEntry.subject_type" @change="newEntry.subject_id = ''">
                <option value="DEPARTMENT">部门</option>
                <option value="ROLE">角色</option>
                <option value="USER">用户</option>
              </select>
              <select v-model="newEntry.subject_id">
                <option value="">选择对象</option>
                <option v-for="option in subjectOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
              </select>
              <select v-model="newEntry.permission"><option value="READ">可查看</option><option value="MANAGE">可管理</option></select>
              <button type="button" class="secondary-action" @click="addAclEntry">添加授权</button>
            </div>
          </div>

          <div class="governance-form" style="margin-top:16px">
            <label>资料敏感级别
              <select v-model="sensitivity">
                <option v-for="(label, key) in SENSITIVITY_LABELS" :key="key" :value="key">{{ label }}（{{ key }}）</option>
              </select>
            </label>
            <label class="assistant-checkboxes" style="flex-direction:row">
              <input v-model="externalAllowed" type="checkbox">允许发送外部大模型（DeepSeek）
            </label>
            <p class="assistant-hint">该设置只影响外部 DeepSeek，不影响本地千问。CONFIDENTIAL、RESTRICTED 始终禁止外发；任一条引用禁止外发时整次不调用外部模型。</p>
          </div>

          <div class="form-actions">
            <button type="button" class="secondary-action" @click="saveExternalPolicy">保存外部模型策略</button>
            <button type="button" @click="saveAccess">保存访问权限</button>
          </div>
        </template>
      </section>
    </section>
  </div>
</template>
