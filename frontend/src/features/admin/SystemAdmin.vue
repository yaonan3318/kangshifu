<script setup lang="ts">
import { computed, inject, onMounted, ref, watch, type Ref } from 'vue'
import type { AuthUser } from '../../api/auth'
import UserAdmin from './UserAdmin.vue'
import DepartmentAdmin from './DepartmentAdmin.vue'
import RoleAdmin from './RoleAdmin.vue'
import AuditAdmin from './AuditAdmin.vue'
import AssistantManager from '../assistants/AssistantManager.vue'
import ChatflowManager from '../assistants/ChatflowManager.vue'
import FeedbackAdmin from '../feedback/FeedbackAdmin.vue'
import StatsAdmin from '../stats/StatsAdmin.vue'
import KnowledgeGapAdmin from '../stats/KnowledgeGapAdmin.vue'
import { hasPermission, type PermissionCode } from '../../utils/permissions'

type TabKey = 'users' | 'departments' | 'roles' | 'assistants' | 'chatflows' | 'feedback' | 'gaps' | 'audit' | 'stats'
const LAST_SYSTEM_TAB_PREFIX = 'company-search:last-system-tab:'

const tab = ref<TabKey>('users')
const currentUser = inject<Ref<AuthUser | null>>('currentUser', ref(null))

interface TabDef {
  key: TabKey
  label: string
  component: unknown
  permission?: PermissionCode
  superOnly?: boolean
}

const tabs: TabDef[] = [
  { key: 'users', label: '用户', component: UserAdmin, permission: 'IDENTITY_MANAGE' },
  { key: 'departments', label: '部门', component: DepartmentAdmin, permission: 'IDENTITY_MANAGE' },
  { key: 'roles', label: '角色', component: RoleAdmin, permission: 'IDENTITY_MANAGE' },
  { key: 'assistants', label: '助手', component: AssistantManager, permission: 'ASSISTANT_MANAGE' },
  { key: 'chatflows', label: '流程', component: ChatflowManager, permission: 'ASSISTANT_MANAGE' },
  { key: 'feedback', label: '反馈', component: FeedbackAdmin, superOnly: true },
  { key: 'gaps', label: '知识缺口', component: KnowledgeGapAdmin, permission: 'STATS_VIEW' },
  { key: 'audit', label: '审计', component: AuditAdmin, permission: 'AUDIT_VIEW' },
  { key: 'stats', label: '统计', component: StatsAdmin, permission: 'STATS_VIEW' },
]

const visibleTabs = computed(() => tabs.filter((item) => {
  if (item.superOnly) return Boolean(currentUser.value?.is_super_admin)
  return item.permission ? hasPermission(item.permission) : true
}))

const activeComponent = computed(
  () => visibleTabs.value.find((item) => item.key === tab.value)?.component ?? visibleTabs.value[0]?.component,
)

function storageKey(): string | null {
  return currentUser.value ? `${LAST_SYSTEM_TAB_PREFIX}${currentUser.value.id}` : null
}

onMounted(() => {
  const key = storageKey()
  const stored = key ? window.localStorage.getItem(key) as TabKey | null : null
  if (stored && visibleTabs.value.some((item) => item.key === stored)) tab.value = stored
  else if (!visibleTabs.value.some((item) => item.key === tab.value)) tab.value = visibleTabs.value[0]?.key ?? 'users'
})

watch(visibleTabs, (items) => {
  if (!items.some((item) => item.key === tab.value)) tab.value = items[0]?.key ?? 'users'
})

watch(tab, (value) => {
  const key = storageKey()
  if (key) window.localStorage.setItem(key, value)
})
</script>

<template>
  <div class="system-admin">
    <nav class="system-tabs" aria-label="系统管理">
      <button
        v-for="item in visibleTabs"
        :key="item.key"
        :class="{ active: tab === item.key }"
        @click="tab = item.key"
      >{{ item.label }}</button>
    </nav>
    <KeepAlive>
      <component :is="activeComponent" :key="tab" />
    </KeepAlive>
  </div>
</template>
