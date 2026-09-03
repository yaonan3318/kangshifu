<script setup lang="ts">
import { ref } from 'vue'
import AnswerPage from './features/answer/AnswerPage.vue'
import DocumentLibrary from './features/documents/DocumentLibrary.vue'
import SearchPage from './features/search/SearchPage.vue'

const page = ref<'answer' | 'search' | 'library'>('answer')
</script>

<template>
  <nav class="top-nav" aria-label="主导航">
    <button :class="{ active: page === 'answer' }" @click="page = 'answer'">知识问答</button>
    <button :class="{ active: page === 'search' }" @click="page = 'search'">资料检索</button>
    <button :class="{ active: page === 'library' }" @click="page = 'library'">资料库</button>
  </nav>
  <AnswerPage v-if="page === 'answer'" />
  <SearchPage v-else-if="page === 'search'" />
  <DocumentLibrary v-else />
</template>
