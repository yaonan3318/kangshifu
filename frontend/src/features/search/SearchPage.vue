<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { searchDocuments } from '../../api/search'
import type { SearchResult } from '../../types/search'
import type { SearchDiagnostics } from '../../types/search'
import { listKnowledgeBases } from '../../api/knowledgeBases'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'

const query = ref('')
const extension = ref('')
const documentName = ref('')
const createdFrom = ref('')
const createdTo = ref('')
const results = ref<SearchResult[]>([])
const loading = ref(false)
const searched = ref(false)
const error = ref('')
const diagnostics = ref<SearchDiagnostics|null>(null)
const knowledgeBases=ref<KnowledgeBaseRecord[]>([])
const knowledgeBaseId=ref('')
const tags=ref('')
const departmentId=ref('')
const ownerUserId=ref('')
const documentStatus=ref('')
const relativePath=ref('')
const versionNumber=ref('')
const validOnly=ref(false)

const types = ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'md', 'csv', 'png', 'jpg']
const statuses = ['READY', 'PENDING', 'PARSING', 'INDEX_FAILED', 'PARSE_FAILED']
const matchLabels = { keyword: '关键词', vector: '语义', hybrid: '混合命中' }

function sourceLabel(item: SearchResult): string {
  if (item.page_start) return item.page_end && item.page_end !== item.page_start ? `第 ${item.page_start}–${item.page_end} 页` : `第 ${item.page_start} 页`
  if (item.slide_number) return `第 ${item.slide_number} 张幻灯片`
  if (item.sheet_name) {
    const rows = item.row_start ? ` · 第 ${item.row_start}${item.row_end && item.row_end !== item.row_start ? `–${item.row_end}` : ''} 行` : ''
    return `${item.sheet_name}${rows}`
  }
  return `片段 ${item.sequence_number}`
}

async function search() {
  const value = query.value.trim()
  if (!value) return
  loading.value = true
  error.value = ''
  try {
    const response = await searchDocuments(value, {
      extension: extension.value, documentName: documentName.value,
      createdFrom: createdFrom.value, createdTo: createdTo.value,
      knowledgeBaseId:knowledgeBaseId.value,tags:tags.value.split(',').map(x=>x.trim()).filter(Boolean),
      departmentId: departmentId.value.trim(), ownerUserId: ownerUserId.value.trim(),
      documentStatus: documentStatus.value, relativePath: relativePath.value.trim(),
      versionNumber: versionNumber.value, validOnly: validOnly.value,
    })
    results.value = response.items
    diagnostics.value=response.diagnostics
    searched.value = true
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '检索失败，请确认本地服务正常运行'
  } finally {
    loading.value = false
  }
}
onMounted(async()=>{try{knowledgeBases.value=(await listKnowledgeBases()).items}catch{/* 搜索仍可在全部知识库范围运行 */}})
</script>

<template>
  <main class="app-shell search-shell">
    <header class="hero search-hero">
      <p class="eyebrow">HYBRID SEARCH · LOCAL</p>
      <h1>检索公司资料</h1>
      <p>同时使用精确关键词和语义理解，从已经完成索引的本地文档中寻找相关片段。</p>
    </header>
    <section class="search-panel" aria-labelledby="search-title">
      <h2 id="search-title" class="visually-hidden">资料检索</h2>
      <form class="search-form" @submit.prevent="search">
        <label class="search-query"><span>检索内容</span><input v-model="query" type="search" placeholder="例如：Go 服务如何通过 Jenkins 部署到 K8s？" maxlength="1000"></label>
        <label><span>知识库</span><select v-model="knowledgeBaseId"><option value="">全部知识库</option><option v-for="item in knowledgeBases.filter(x=>x.enabled)" :key="item.id" :value="item.id">{{item.name}}</option></select></label>
        <label><span>文件类型</span><select v-model="extension"><option value="">全部类型</option><option v-for="type in types" :key="type" :value="type">{{ type.toUpperCase() }}</option></select></label>
        <button type="submit" :disabled="loading || !query.trim()">{{ loading ? '检索中…' : '开始检索' }}</button>
        <details class="advanced-filters">
          <summary>更多筛选</summary>
          <div><label><span>文件名包含</span><input v-model="documentName" type="text" placeholder="可选"></label><label><span>标签</span><input v-model="tags" placeholder="多个标签用逗号分隔"></label><label><span>开始日期</span><input v-model="createdFrom" type="date"></label><label><span>结束日期</span><input v-model="createdTo" type="date"></label><label><span>文档状态</span><select v-model="documentStatus"><option value="">全部状态</option><option v-for="item in statuses" :key="item" :value="item">{{ item }}</option></select></label><label><span>文件夹路径</span><input v-model="relativePath" type="text" placeholder="如 技术部/"></label><label><span>文档版本</span><input v-model="versionNumber" type="number" min="1" placeholder="可选"></label><label><span>部门 ID</span><input v-model="departmentId" type="text" placeholder="可选，UUID"></label><label><span>上传人 ID</span><input v-model="ownerUserId" type="text" placeholder="可选，UUID"></label><label class="admin-check-row"><input v-model="validOnly" type="checkbox"><span>仅看有效期内的文档</span></label></div>
        </details>
      </form>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </section>
    <section v-if="searched || loading" class="results-panel" aria-live="polite">
      <div class="section-heading"><div><p class="eyebrow">RESULTS</p><h2>相关片段 <span>{{ results.length }}</span></h2></div></div>
      <div v-if="diagnostics&&!loading" class="diagnostic-summary"><span>{{diagnostics.mode==='hybrid_rerank'?'混合检索 + 本地精排':'混合检索（RRF）'}}</span><span>{{diagnostics.timings_ms.total||0}} ms</span><span v-if="diagnostics.expanded_terms.length">扩展：{{diagnostics.expanded_terms.join('、')}}</span></div><p v-if="diagnostics?.warning" class="warning-note">{{diagnostics.warning}}</p>
      <p v-if="loading" class="search-empty">正在本机计算查询向量并检索…</p>
      <p v-else-if="!results.length" class="search-empty">{{diagnostics?.no_answer_reason||'没有找到相关内容。请换一种说法，或确认文档状态已经变为“可检索”。'}}</p>
      <ol v-else class="result-list">
        <li v-for="item in results" :key="item.chunk_id" class="result-card">
          <header>
            <div><strong>{{ item.document_name }}</strong><p>{{ sourceLabel(item) }}<template v-if="item.section_path.length"> · {{ item.section_path.join(' / ') }}</template></p></div>
            <div class="result-badges"><span>可信度 {{Math.round(item.final_score*100)}}%</span><span :class="`match-${item.match_type}`">{{ matchLabels[item.match_type] }}</span><span v-if="item.ocr_confidence !== null">OCR {{ Math.round(item.ocr_confidence * 100) }}%</span><span>{{ item.extension.toUpperCase() }}</span></div>
          </header>
          <p class="result-content">{{ item.content }}</p>
        </li>
      </ol>
    </section>
  </main>
</template>
