<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ApiError, deleteDocument, listDocuments, setDocumentEnabled } from '../../api/documents'
import type { DocumentRecord } from '../../types/documents'
import DocumentTable from './DocumentTable.vue'
import DocumentDetail from './DocumentDetail.vue'
import UploadQueue from './UploadQueue.vue'
import BatchImport from './BatchImport.vue'
import BatchList from './BatchList.vue'
import BatchDetail from './BatchDetail.vue'
import { listBatches } from '../../api/batches'
import type { BatchRecord } from '../../types/batches'
import { listKnowledgeBases } from '../../api/knowledgeBases'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
import KnowledgeBaseManager from './KnowledgeBaseManager.vue'
import RecycleBin from './RecycleBin.vue'

const documents = ref<DocumentRecord[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const query = ref('')
const extension = ref('')
const page = ref(1)
const pageSize = 25
const selectedDocument = ref<DocumentRecord | null>(null)
const libraryMode = ref<'single'|'batch'|'history'>('single')
const batches = ref<BatchRecord[]>([])
const selectedBatch = ref<string | null>(null)
const knowledgeBases = ref<KnowledgeBaseRecord[]>([])
const knowledgeBaseId = ref('')
const showKnowledgeBases = ref(false)
const showRecycleBin = ref(false)
let searchTimer: number | undefined
let pollTimer: number | undefined

const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const knowledgeBaseNames = computed(()=>Object.fromEntries(knowledgeBases.value.map(item=>[item.id,item.name])))

async function refresh(silent = false) {
  if (!silent) loading.value = true
  error.value = ''
  const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) })
  if (query.value.trim()) params.set('query', query.value.trim())
  if (extension.value) params.set('extension', extension.value)
  if (knowledgeBaseId.value) params.set('knowledge_base_id',knowledgeBaseId.value)
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

async function refreshBatches() {
  try { batches.value = (await listBatches()).items } catch (reason) { error.value = reason instanceof Error ? reason.message : '无法读取导入批次' }
}
async function refreshKnowledgeBases(){try{knowledgeBases.value=(await listKnowledgeBases()).items;if(!knowledgeBaseId.value)knowledgeBaseId.value=knowledgeBases.value.find(x=>x.enabled)?.id||''}catch(reason){error.value=reason instanceof Error?reason.message:'无法读取知识库'}}

async function batchCreated(id: string) { await refreshBatches(); selectedBatch.value = id; libraryMode.value = 'history'; await refresh() }

watch([query, extension, knowledgeBaseId], () => {
  page.value = 1
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(refresh, 250)
})
watch(page, () => refresh())

async function remove(document: DocumentRecord) {
  if (!window.confirm(`确定将“${document.original_name}”移入回收站吗？资料将立即停止参与检索。`)) return
  try {
    await deleteDocument(document.id)
    if (documents.value.length === 1 && page.value > 1) page.value -= 1
    else await refresh()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '删除失败'
  }
}
async function toggle(document:DocumentRecord){try{await setDocumentEnabled(document.id,!document.enabled);await refresh()}catch(reason){error.value=reason instanceof ApiError?reason.message:'操作失败'}}

onMounted(() => {
  refresh()
  refreshBatches()
  refreshKnowledgeBases()
  pollTimer = window.setInterval(() => {
    if (documents.value.some((item) => ['PENDING', 'PARSING', 'CHUNKING', 'PARSED', 'EMBEDDING', 'INDEXING'].includes(item.status))) refresh(true)
  }, 2000)
})
onUnmounted(() => window.clearInterval(pollTimer))
</script>

<template>
  <main class="app-shell">
    <header class="hero"><p class="eyebrow">COMPANY SEARCH · LOCAL</p><h1>本地资料库</h1><p>文件只保存在这台 Mac 上。上传后会自动完成解析、OCR、切片和本地索引。</p></header>
    <nav class="library-modes" aria-label="导入方式"><button :class="{active:libraryMode==='single'}" @click="libraryMode='single'">单文件上传</button><button :class="{active:libraryMode==='batch'}" @click="libraryMode='batch'">批量导入</button><button :class="{active:libraryMode==='history'}" @click="libraryMode='history';refreshBatches()">导入批次</button><button @click="showKnowledgeBases=true">管理知识库</button><button @click="showRecycleBin=true">回收站</button></nav>
    <UploadQueue v-if="libraryMode==='single'" :knowledge-bases="knowledgeBases" :knowledge-base-id="knowledgeBaseId" @uploaded="refresh" />
    <BatchImport v-else-if="libraryMode==='batch'" :knowledge-bases="knowledgeBases" :knowledge-base-id="knowledgeBaseId" @created="batchCreated" />
    <BatchList v-else :batches="batches" @open="selectedBatch=$event" />
    <section class="library-panel" aria-labelledby="library-title">
      <div class="section-heading"><div><p class="eyebrow">LIBRARY</p><h2 id="library-title">已托管文件 <span>{{ total }}</span></h2></div></div>
      <div class="filters"><label><span>知识库</span><select v-model="knowledgeBaseId"><option value="">全部知识库</option><option v-for="item in knowledgeBases" :key="item.id" :value="item.id">{{item.name}}{{item.enabled?'':'（停用）'}}</option></select></label><label><span>文件名</span><input v-model="query" type="search" placeholder="输入文件名"></label><label><span>类型</span><select v-model="extension"><option value="">全部类型</option><option v-for="type in ['pdf','docx','xlsx','pptx','txt','md','csv','png','jpg']" :key="type" :value="type">{{ type.toUpperCase() }}</option></select></label></div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <DocumentTable :documents="documents" :loading="loading" :knowledge-base-names="knowledgeBaseNames" @delete="remove" @toggle="toggle" @view="selectedDocument = $event" />
      <nav v-if="pages > 1" class="pagination" aria-label="分页"><button :disabled="page === 1" @click="page--">上一页</button><span>第 {{ page }} / {{ pages }} 页</span><button :disabled="page === pages" @click="page++">下一页</button></nav>
    </section>
    <DocumentDetail v-if="selectedDocument" :document="selectedDocument" :knowledge-bases="knowledgeBases" @close="selectedDocument = null" @changed="refresh" />
    <BatchDetail v-if="selectedBatch" :id="selectedBatch" @close="selectedBatch=null" @changed="refreshBatches();refresh()" />
    <KnowledgeBaseManager v-if="showKnowledgeBases" :items="knowledgeBases" @close="showKnowledgeBases=false" @changed="refreshKnowledgeBases();refresh()" />
    <RecycleBin v-if="showRecycleBin" @close="showRecycleBin=false" @changed="refreshKnowledgeBases();refresh()" />
  </main>
</template>
