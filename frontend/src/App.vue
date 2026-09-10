<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import Dashboard from './features/dashboard/Dashboard.vue'
import AnswerPage from './features/answer/AnswerPage.vue'
import DocumentLibrary from './features/documents/DocumentLibrary.vue'
import SearchPage from './features/search/SearchPage.vue'
import RetrievalLab from './features/search/RetrievalLab.vue'
import SystemAdmin from './features/admin/SystemAdmin.vue'
import LoginPanel from './components/LoginPanel.vue'
import { getAuthState, logoutRequest, type AuthUser } from './api/auth'
import { clearPermissions, hasAnyPermission, hasPermission, setPermissions } from './utils/permissions'

type PageKey = 'dashboard' | 'answer' | 'search' | 'library' | 'lab' | 'system'
const LAST_PAGE_PREFIX = 'company-search:last-page:'

const page = ref<PageKey>('dashboard')
const currentUser = ref<AuthUser | null>(null)
const checking = ref(true)
const sessionStarted = ref(false)

const isSuper = computed(() => Boolean(currentUser.value?.is_super_admin))

const pages: Record<PageKey, unknown> = {
  dashboard: Dashboard,
  answer: AnswerPage,
  search: SearchPage,
  library: DocumentLibrary,
  lab: RetrievalLab,
  system: SystemAdmin,
}

const activePage = computed(() => pages[page.value])

const SYSTEM_PERMISSIONS = ['IDENTITY_MANAGE', 'ASSISTANT_MANAGE', 'AUDIT_VIEW', 'STATS_VIEW'] as const

const navItems = computed(() => {
  const items: Array<{ key: PageKey; label: string }> = [{ key: 'dashboard', label: '首页' }]
  if (hasPermission('ANSWER_USE')) items.push({ key: 'answer', label: '知识问答' })
  if (hasPermission('SEARCH_USE')) items.push({ key: 'search', label: '资料检索' })
  if (hasPermission('DOCUMENT_VIEW')) items.push({ key: 'library', label: '资料库' })
  if (hasPermission('RETRIEVAL_LAB_USE')) items.push({ key: 'lab', label: '检索实验室' })
  if (isSuper.value || hasAnyPermission([...SYSTEM_PERMISSIONS])) items.push({ key: 'system', label: '系统管理' })
  return items
})

function isPageAllowed(target: PageKey, user: AuthUser | null = currentUser.value): boolean {
  if (!(target in pages)) return false
  if (target === 'dashboard') return true
  if (target === 'answer') return hasPermission('ANSWER_USE')
  if (target === 'search') return hasPermission('SEARCH_USE')
  if (target === 'library') return hasPermission('DOCUMENT_VIEW')
  if (target === 'lab') return hasPermission('RETRIEVAL_LAB_USE')
  if (target === 'system') return Boolean(user?.is_super_admin) || hasAnyPermission([...SYSTEM_PERMISSIONS])
  return false
}

const PAGE_ORDER: PageKey[] = ['dashboard', 'answer', 'search', 'library', 'lab', 'system']

function defaultPageFor(user: AuthUser | null): PageKey {
  return PAGE_ORDER.find((key) => isPageAllowed(key, user)) ?? 'answer'
}

function restorePageForUser(user: AuthUser | null) {
  if (!user) {
    page.value = 'dashboard'
    return
  }
  const stored = window.localStorage.getItem(`${LAST_PAGE_PREFIX}${user.id}`) as PageKey | null
  page.value = stored && isPageAllowed(stored, user) ? stored : defaultPageFor(user)
}

provide('currentUser', currentUser)

function onSwitchPage(event: Event) {
  const target = (event as CustomEvent<string>).detail
  if (target in pages && isPageAllowed(target as PageKey)) page.value = target as PageKey
}

function onAuthExpired() {
  currentUser.value = null
  clearPermissions()
}

async function boot() {
  checking.value = true
  try {
    const state = await getAuthState()
    currentUser.value = state.user
    setPermissions(state.user?.permissions)
    restorePageForUser(state.user)
  } catch {
    currentUser.value = null
    clearPermissions()
    page.value = 'dashboard'
  } finally {
    checking.value = false
  }
}

async function handleLogin() {
  await boot()
}

async function handleLogout() {
  try {
    await logoutRequest()
  } finally {
    currentUser.value = null
    clearPermissions()
    sessionStarted.value = false
    page.value = 'dashboard'
  }
}

watch(currentUser, (user) => {
  if (user) sessionStarted.value = true
})
watch(page, (value) => {
  const user = currentUser.value
  if (user && isPageAllowed(value, user)) {
    window.localStorage.setItem(`${LAST_PAGE_PREFIX}${user.id}`, value)
  }
})

onMounted(() => {
  void boot()
  window.addEventListener('company-switch-page', onSwitchPage)
  window.addEventListener('company-auth-expired', onAuthExpired)
})
onUnmounted(() => {
  window.removeEventListener('company-switch-page', onSwitchPage)
  window.removeEventListener('company-auth-expired', onAuthExpired)
})
</script>

<template>
  <div v-if="checking" class="login-boot">正在连接本地服务…</div>
  <template v-else>
    <div v-if="currentUser || sessionStarted" v-show="!!currentUser" class="app-root">
      <header class="app-header">
        <button type="button" class="app-brand" aria-label="返回知识问答" @click="page = 'answer'">
          <span class="app-brand-mark">康</span>
          <span><strong>康师傅知识助手</strong><small>企业知识工作台</small></span>
        </button>
        <nav class="top-nav" aria-label="主导航">
          <button
            v-for="item in navItems"
            :key="item.key"
            :class="{ active: page === item.key }"
            @click="page = item.key"
          >{{ item.label }}</button>
        </nav>
        <div class="top-user">
          <span class="user-avatar-chip">{{ currentUser?.display_name?.slice(0, 1) || '用' }}</span>
          <span class="user-chip">{{ currentUser?.display_name }}<em v-if="currentUser?.is_super_admin">管理员</em></span>
          <button type="button" class="logout-button" @click="handleLogout">退出</button>
        </div>
      </header>
      <KeepAlive>
        <component :is="activePage" />
      </KeepAlive>
    </div>
    <div v-if="!currentUser" class="login-overlay">
      <LoginPanel @login="handleLogin" />
    </div>
  </template>
</template>
