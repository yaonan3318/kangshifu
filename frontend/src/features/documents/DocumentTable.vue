<script setup lang="ts">
import { downloadUrl } from '../../api/documents'
import type { DocumentRecord } from '../../types/documents'

defineProps<{ documents: DocumentRecord[]; loading: boolean }>()
const emit = defineEmits<{ delete: [document: DocumentRecord]; view: [document: DocumentRecord] }>()

const statusLabels: Record<DocumentRecord['status'], string> = {
  PENDING: '等待处理', PARSING: '解析中', CHUNKING: '切片中', PARSED: '已解析',
  PARSE_FAILED: '解析失败', OCR_FAILED: 'OCR 失败', DELETING: '删除中',
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead><tr><th>文件</th><th>类型</th><th>大小</th><th>状态</th><th>添加时间</th><th><span class="visually-hidden">操作</span></th></tr></thead>
      <tbody>
        <tr v-if="loading"><td colspan="6" class="empty">正在读取资料库…</td></tr>
        <tr v-else-if="!documents.length"><td colspan="6" class="empty">资料库还是空的，请上传第一份文件。</td></tr>
        <tr v-for="document in documents" v-else :key="document.id">
          <td><strong class="filename">{{ document.original_name }}</strong><small>{{ document.sha256.slice(0, 12) }}…</small></td>
          <td class="uppercase">{{ document.extension }}</td>
          <td>{{ formatBytes(document.size_bytes) }}</td>
          <td><span class="status-dot" :class="`status-${document.status.toLowerCase()}`"></span>{{ statusLabels[document.status] }}</td>
          <td>{{ formatDate(document.created_at) }}</td>
          <td class="row-actions"><button type="button" @click="emit('view', document)">详情</button><a :href="downloadUrl(document.id)">下载</a><button type="button" class="text-danger" @click="emit('delete', document)">删除</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
