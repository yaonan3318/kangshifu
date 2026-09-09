<script setup lang="ts">
import type { SearchDiagnostics } from '../../types/search'
defineProps<{diagnostics:SearchDiagnostics}>()
const labels:Record<string,string>={keyword:'关键词召回',vector:'语义召回',fusion:'RRF 融合',rerank:'精排结果',final:'最终上下文'}
</script>
<template><section class="retrieval-stages"><div class="diagnostic-summary"><span>模式：{{diagnostics.mode==='hybrid_rerank'?'混合检索 + 本地精排':'混合检索（RRF）'}}</span><span>总耗时：{{diagnostics.timings_ms.total||0}} ms</span><span v-if="diagnostics.expanded_terms.length">扩展词：{{diagnostics.expanded_terms.join('、')}}</span></div><p v-if="diagnostics.warning" class="warning-note">{{diagnostics.warning}}</p><p v-if="diagnostics.no_answer_reason" class="warning-note">{{diagnostics.no_answer_reason}}</p><details v-for="(items,key) in diagnostics.stages" :key="key"><summary>{{labels[key]||key}} · {{items.length}}</summary><ol><li v-for="item in items" :key="`${key}-${item.chunk_id}`"><div><strong>{{item.document_name}}</strong><span>片段 {{item.sequence_number}} · {{item.score.toFixed(4)}}</span></div><p>{{item.content_preview}}</p></li></ol></details></section></template>
