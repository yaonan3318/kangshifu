<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import AnswerPage from './features/answer/AnswerPage.vue'
import DocumentLibrary from './features/documents/DocumentLibrary.vue'
import SearchPage from './features/search/SearchPage.vue'
import RetrievalLab from './features/search/RetrievalLab.vue'
import SystemAdmin from './features/admin/SystemAdmin.vue'
import LoginPanel from './components/LoginPanel.vue'
import { getAuthState, logoutRequest, type AuthUser } from './api/auth'

type PageKey = 'answer' | 'search' | 'library' | 'lab' | 'system'

const page = ref<PageKey>('answer')
const currentUser = ref<AuthUser | null>(null)
const checking = ref(true)
const sessionStarted = ref(false)

const isSuper = computed(() => Boolean(currentUser.value?.is_super_admin))

const pages: Record<PageKey, unknown> = {
  answer: AnswerPage,
  search: SearchPage,
  library: DocumentLibrary,
  lab: RetrievalLab,
  system: SystemAdmin,
}

const activePage = computed(() => pages[page.value])

const navItems = computed(() => {
  const items: Array<{ key: PageKey; label: string }> = [
    { key: 'answer', label: '知识问答' },
    { key: 'search', label: '资料检索' },
    { key: 'library', label: '资料库' },
  ]
  if (isSuper.value) {
    items.push({ key: 'lab', label: '检索实验室' })
    items.push({ key: 'system', label: '系统管理' })
  }
  return items
})

provide('currentUser', currentUser)

function onSwitchPage(event: Event) {
  const target = (event as CustomEvent<string>).detail
  if (target in pages) page.value = target as PageKey
}

function onAuthExpired() {
  currentUser.value = null
}

async function boot() {
  checking.value = true
  try {
    const state = await getAuthState()
    currentUser.value = state.user
  } catch {
    currentUser.value = null
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
    sessionStarted.value = false
    page.value = 'answer'
  }
}

watch(currentUser, (user) => {
  if (user) sessionStarted.value = true
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
