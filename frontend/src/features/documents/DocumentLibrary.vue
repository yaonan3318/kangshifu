<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ApiError, deleteDocument, listDocuments } from '../../api/documents'
import type { DocumentRecord } from '../../types/documents'
import DocumentTable from './DocumentTable.vue'
import DocumentDetail from './DocumentDetail.vue'
import UploadQueue from './UploadQueue.vue'

const documents = ref<DocumentRecord[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const query = ref('')
const extension = ref('')
const page = ref(1)
const pageSize = 25
const selectedDocument = ref<DocumentRecord | null>(null)
let searchTimer: number | undefined
let pollTimer: number | undefined

const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function refresh(silent = false) {
  if (!silent) loading.value = true
  error.value = ''
  const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) })
  if (query.value.trim()) params.set('query', query.value.trim())
  if (extension.value) params.set('extension', extension.value)
  try {
    const result = await listDocuments(params)
    documents.value = result.items
    total.value = result.total
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '无法读取资料库'
  } finally {
    if (!silent) loading.value = false
  }
}

watch([query, extension], () => {
  page.value = 1
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refresh, 250)
})
watch(page, () => refresh())

async function remove(document: DocumentRecord) {
  if (!window.confirm(`确定删除“${document.original_name}”吗？原文件也会被删除。`)) return
  try {
    await deleteDocument(document.id)
    if (documents.value.length === 1 && page.value > 1) page.value -= 1
    else await refresh()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '删除失败'
  }
}

onMounted(() => {
  refresh()
  pollTimer = window.setInterval(() => {
    if (documents.value.some((item) => ['PENDING', 'PARSING', 'CHUNKING'].includes(item.status))) refresh(true)
  }, 2000)
})
onUnmounted(() => window.clearInterval(pollTimer))
</script>

<template>
  <main class="app-shell">
    <header class="hero"><p class="eyebrow">COMPANY SEARCH · LOCAL</p><h1>本地资料库</h1><p>文件只保存在这台 Mac 上。上传完成后，后续阶段将加入解析和检索。</p></header>
    <UploadQueue @uploaded="refresh" />
    <section class="library-panel" aria-labelledby="library-title">
      <div class="section-heading"><div><p class="eyebrow">LIBRARY</p><h2 id="library-title">已托管文件 <span>{{ total }}</span></h2></div></div>
      <div class="filters"><label><span>文件名</span><input v-model="query" type="search" placeholder="输入文件名"></label><label><span>类型</span><select v-model="extension"><option value="">全部类型</option><option v-for="type in ['pdf','docx','xlsx','pptx','txt','md','csv','png','jpg']" :key="type" :value="type">{{ type.toUpperCase() }}</option></select></label></div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <DocumentTable :documents="documents" :loading="loading" @delete="remove" @view="selectedDocument = $event" />
      <nav v-if="pages > 1" class="pagination" aria-label="分页"><button :disabled="page === 1" @click="page--">上一页</button><span>第 {{ page }} / {{ pages }} 页</span><button :disabled="page === pages" @click="page++">下一页</button></nav>
    </section>
    <DocumentDetail v-if="selectedDocument" :document="selectedDocument" @close="selectedDocument = null" @changed="refresh" />
  </main>
</template>
