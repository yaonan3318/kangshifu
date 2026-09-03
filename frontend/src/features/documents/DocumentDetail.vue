<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, getDocumentContent, reprocessDocument } from '../../api/documents'
import type { DocumentChunk, DocumentRecord } from '../../types/documents'

const props = defineProps<{ document: DocumentRecord }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const chunks = ref<DocumentChunk[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const pageSize = 10
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function source(chunk: DocumentChunk): string {
  if (chunk.page_start) return `第 ${chunk.page_start}${chunk.page_end && chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ''} 页`
  if (chunk.slide_number) return `幻灯片 ${chunk.slide_number}`
  if (chunk.sheet_name) return `${chunk.sheet_name}${chunk.row_start ? ` · 第 ${chunk.row_start}${chunk.row_end && chunk.row_end !== chunk.row_start ? `–${chunk.row_end}` : ''} 行` : ''}`
  return `片段 ${chunk.sequence_number}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await getDocumentContent(props.document.id, page.value, pageSize)
    chunks.value = result.items
    total.value = result.total
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '无法读取解析内容'
  } finally { loading.value = false }
}

async function reprocess() {
  try {
    await reprocessDocument(props.document.id)
    emit('changed')
    emit('close')
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '无法重新处理'
  }
}

watch(() => props.document.id, () => { page.value = 1; load() }, { immediate: true })
watch(page, load)
</script>

<template>
  <div class="detail-backdrop" @click.self="emit('close')">
    <section class="detail-panel" role="dialog" aria-modal="true" aria-labelledby="detail-title">
      <header><div><p class="eyebrow">DOCUMENT</p><h2 id="detail-title">{{ document.original_name }}</h2></div><button class="close-button" type="button" aria-label="关闭" @click="emit('close')">×</button></header>
      <dl><div><dt>状态</dt><dd>{{ document.status }}</dd></div><div><dt>类型</dt><dd>{{ document.extension.toUpperCase() }}</dd></div><div><dt>片段数</dt><dd>{{ total }}</dd></div><div v-if="document.parser_name"><dt>解析器</dt><dd>{{ document.parser_name }} {{ document.parser_version }}</dd></div></dl>
      <p v-if="document.error_message" class="error" role="alert">{{ document.error_message }}</p>
      <div class="detail-actions"><button type="button" @click="reprocess">重新处理</button></div>
      <p v-if="loading" class="empty">正在读取解析内容…</p>
      <p v-else-if="!chunks.length" class="empty">当前还没有解析内容。</p>
      <ol v-else class="chunk-list">
        <li v-for="chunk in chunks" :key="chunk.id"><div class="chunk-meta"><strong>{{ source(chunk) }}</strong><span v-if="chunk.section_path.length">{{ chunk.section_path.join(' / ') }}</span><span v-if="chunk.ocr_confidence !== null">OCR {{ Math.round(chunk.ocr_confidence * 100) }}%</span></div><pre>{{ chunk.content }}</pre></li>
      </ol>
      <nav v-if="pages > 1" class="pagination"><button :disabled="page === 1" @click="page--">上一页</button><span>{{ page }} / {{ pages }}</span><button :disabled="page === pages" @click="page++">下一页</button></nav>
    </section>
  </div>
</template>
