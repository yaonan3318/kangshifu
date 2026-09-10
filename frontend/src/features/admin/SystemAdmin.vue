<script setup lang="ts">
import { computed, ref } from 'vue'
import UserAdmin from './UserAdmin.vue'
import DepartmentAdmin from './DepartmentAdmin.vue'
import RoleAdmin from './RoleAdmin.vue'
import AuditAdmin from './AuditAdmin.vue'
import AssistantManager from '../assistants/AssistantManager.vue'
import FeedbackAdmin from '../feedback/FeedbackAdmin.vue'
import StatsAdmin from '../stats/StatsAdmin.vue'

type TabKey = 'users' | 'departments' | 'roles' | 'assistants' | 'feedback' | 'audit' | 'stats'

const tab = ref<TabKey>('users')

const tabs: Array<{ key: TabKey; label: string; component: unknown }> = [
  { key: 'users', label: '用户', component: UserAdmin },
  { key: 'departments', label: '部门', component: DepartmentAdmin },
  { key: 'roles', label: '角色', component: RoleAdmin },
  { key: 'assistants', label: '助手', component: AssistantManager },
  { key: 'feedback', label: '反馈', component: FeedbackAdmin },
  { key: 'audit', label: '审计', component: AuditAdmin },
  { key: 'stats', label: '统计', component: StatsAdmin },
]

const activeComponent = computed(() => tabs.find((item) => item.key === tab.value)?.component ?? UserAdmin)
</script>

<template>
  <div class="system-admin">
    <nav class="system-tabs" aria-label="系统管理">
      <button
        v-for="item in tabs"
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
