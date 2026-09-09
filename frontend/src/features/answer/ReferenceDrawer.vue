<script setup lang="ts">
import type { CitationSource } from '../../types/answer'

const props = defineProps<{ source: CitationSource | null; knowledgeBaseName?: string }>()
const emit = defineEmits<{ close: []; openDocument: [documentId: string] }>()

function statusText(): string {
  if (props.source?.status === 'DELETED') return '当前资料已删除'
  if (props.source?.status === 'DISABLED') return '当前资料已停用'
  return ''
}
</script>

<template>
  <div v-if="source" class="detail-backdrop" @click.self="emit('close')">
    <section class="detail-panel reference-drawer" role="dialog" aria-modal="true" aria-label="引用资料详情">
      <header>
        <div>
          <p class="eyebrow">CITATION {{ source.citation_number }}</p>
          <h2>{{ source.document_name }}</h2>
          <p v-if="knowledgeBaseName" class="reference-kb">知识库：{{ knowledgeBaseName }}</p>
        </div>
        <button class="close-button" type="button" @click="emit('close')">×</button>
      </header>

      <div class="reference-status">
        <span v-if="source.status === 'ACTIVE'" class="is-active">资料当前可检索</span>
        <span v-else class="is-stale">{{ statusText() }}，以下为回答时的历史快照</span>
        <span v-if="source.score != null">相关度 {{ (source.score * 100).toFixed(1) }}%</span>
        <span>{{ source.location_text }}</span>
      </div>

      <div class="reference-actions">
        <button
          v-if="source.status === 'ACTIVE'"
          type="button"
          class="secondary-action"
          @click="emit('openDocument', source.document_id)"
        >在资料库打开文档</button>
      </div>

      <h3 class="reference-heading">回答时引用的内容</h3>
      <p class="reference-content">{{ source.content }}</p>
    </section>
  </div>
</template>
