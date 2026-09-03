<script setup lang="ts">
import { ref } from 'vue'
import DocumentLibrary from './features/documents/DocumentLibrary.vue'
import SearchPage from './features/search/SearchPage.vue'

const page = ref<'search' | 'library'>('search')
</script>

<template>
  <nav class="top-nav" aria-label="主导航">
    <button :class="{ active: page === 'search' }" @click="page = 'search'">资料检索</button>
    <button :class="{ active: page === 'library' }" @click="page = 'library'">资料库</button>
  </nav>
  <SearchPage v-if="page === 'search'" />
  <DocumentLibrary v-else />
</template>
