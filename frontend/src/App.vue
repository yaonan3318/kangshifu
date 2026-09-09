<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import AnswerPage from './features/answer/AnswerPage.vue'
import DocumentLibrary from './features/documents/DocumentLibrary.vue'
import SearchPage from './features/search/SearchPage.vue'
import RetrievalLab from './features/search/RetrievalLab.vue'

type PageKey = 'answer' | 'search' | 'library' | 'lab'

const page = ref<PageKey>('answer')
const pages: Record<PageKey, typeof AnswerPage> = {
  answer: AnswerPage,
  search: SearchPage,
  library: DocumentLibrary,
  lab: RetrievalLab,
}

const activePage = computed(() => pages[page.value])

function onSwitchPage(event: Event) {
  const target = (event as CustomEvent<string>).detail
  if (target in pages) page.value = target as PageKey
}

onMounted(() => window.addEventListener('company-switch-page', onSwitchPage))
onUnmounted(() => window.removeEventListener('company-switch-page', onSwitchPage))
</script>

<template>
  <nav class="top-nav" aria-label="主导航">
    <button :class="{ active: page === 'answer' }" @click="page = 'answer'">知识问答</button>
    <button :class="{ active: page === 'search' }" @click="page = 'search'">资料检索</button>
    <button :class="{ active: page === 'library' }" @click="page = 'library'">资料库</button>
    <button :class="{ active: page === 'lab' }" @click="page = 'lab'">检索实验室</button>
  </nav>
  <KeepAlive>
    <component :is="activePage" />
  </KeepAlive>
</template>
