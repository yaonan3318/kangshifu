<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, ref } from 'vue'
import AnswerPage from './features/answer/AnswerPage.vue'
import DocumentLibrary from './features/documents/DocumentLibrary.vue'
import SearchPage from './features/search/SearchPage.vue'
import RetrievalLab from './features/search/RetrievalLab.vue'
import AssistantManager from './features/assistants/AssistantManager.vue'
import FeedbackAdmin from './features/feedback/FeedbackAdmin.vue'
import LoginPanel from './components/LoginPanel.vue'
import { getAuthState, logoutRequest, type AuthUser } from './api/auth'

type PageKey = 'answer' | 'search' | 'library' | 'lab' | 'assistants' | 'feedback'

const page = ref<PageKey>('answer')
const currentUser = ref<AuthUser | null>(null)
const checking = ref(true)

const isSuper = computed(() => Boolean(currentUser.value?.is_super_admin))

const pages: Record<PageKey, unknown> = {
  answer: AnswerPage,
  search: SearchPage,
  library: DocumentLibrary,
  lab: RetrievalLab,
  assistants: AssistantManager,
  feedback: FeedbackAdmin,
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
    items.push({ key: 'assistants', label: '助手管理' })
    items.push({ key: 'feedback', label: '反馈管理' })
  }
  return items
})

provide('currentUser', currentUser)

function onSwitchPage(event: Event) {
  const target = (event as CustomEvent<string>).detail
  if (target in pages) page.value = target as PageKey
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
    page.value = 'answer'
  }
}

onMounted(() => {
  void boot()
  window.addEventListener('company-switch-page', onSwitchPage)
})
onUnmounted(() => window.removeEventListener('company-switch-page', onSwitchPage))
</script>

<template>
  <div v-if="checking" class="login-boot">正在连接本地服务…</div>
  <LoginPanel v-else-if="!currentUser" @login="handleLogin" />
  <template v-else>
    <nav class="top-nav" aria-label="主导航">
      <button
        v-for="item in navItems"
        :key="item.key"
        :class="{ active: page === item.key }"
        @click="page = item.key"
      >{{ item.label }}</button>
    </nav>
    <div class="top-user">
      <span class="user-chip">{{ currentUser.display_name }}<em v-if="currentUser.is_super_admin">管理员</em></span>
      <button type="button" class="logout-button" @click="handleLogout">退出登录</button>
    </div>
    <KeepAlive>
      <component :is="activePage" />
    </KeepAlive>
  </template>
</template>
