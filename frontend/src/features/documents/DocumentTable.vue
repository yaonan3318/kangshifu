<script setup lang="ts">
import { downloadUrl } from '../../api/documents'
import type { DocumentRecord } from '../../types/documents'
import { hasPermission } from '../../utils/permissions'

defineProps<{ documents: DocumentRecord[]; loading: boolean; knowledgeBaseNames: Record<string,string> }>()
const emit = defineEmits<{ delete: [document: DocumentRecord]; view: [document: DocumentRecord]; toggle: [document: DocumentRecord] }>()

const statusLabels: Record<DocumentRecord['status'], string> = {
  PENDING: '等待处理', PARSING: '解析中', CHUNKING: '切片中', PARSED: '已解析',
  EMBEDDING: '向量化中', INDEXING: '建立索引', READY: '可检索', INDEX_FAILED: '索引失败',
  PARSE_FAILED: '解析失败', OCR_FAILED: 'OCR 失败', DELETING: '删除中',
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead><tr><th>文件</th><th>知识库</th><th>版本/片段</th><th>类型</th><th>状态</th><th>添加时间</th><th><span class="visually-hidden">操作</span></th></tr></thead>
      <tbody>
        <tr v-if="loading"><td colspan="7" class="empty">正在读取资料库…</td></tr>
        <tr v-else-if="!documents.length"><td colspan="7" class="empty">资料库还是空的，请上传第一份文件。</td></tr>
        <tr v-for="document in documents" v-else :key="document.id">
          <td><strong class="filename">{{ document.original_name }}</strong><small>{{document.relative_path||document.sha256.slice(0,12)}}<template v-if="document.tags.length"> · {{document.tags.join('、')}}</template></small></td>
          <td>{{knowledgeBaseNames[document.knowledge_base_id]||'未知'}}</td>
          <td>v{{document.version_number}} · {{document.chunk_count}}</td>
          <td class="uppercase">{{ document.extension }}</td>
          <td><span class="status-dot" :class="`status-${document.status.toLowerCase()}`"></span>{{ document.enabled?statusLabels[document.status]:'已停用' }}</td>
          <td>{{ formatDate(document.created_at) }}</td>
          <td class="row-actions"><button type="button" @click="emit('view', document)">详情</button><button v-if="hasPermission('DOCUMENT_MANAGE')" type="button" @click="emit('toggle',document)">{{document.enabled?'停用':'启用'}}</button><a :href="downloadUrl(document.id)">下载</a><button v-if="hasPermission('DOCUMENT_MANAGE')" type="button" class="text-danger" @click="emit('delete', document)">移入回收站</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
