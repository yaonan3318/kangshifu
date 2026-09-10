<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { listAuditLogs } from '../../api/audit'
import type { AuditLogRecord } from '../../types/audit'
import { errorMessage } from '../../utils/errors'

const items = ref<AuditLogRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)
const error = ref('')
const expanded = ref('')

const filters = reactive({
  username: '',
  action: '',
  target_type: '',
  success: '',
  created_from: '',
  created_to: '',
})

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const result = await listAuditLogs({
      username: filters.username || undefined,
      action: filters.action || undefined,
      target_type: filters.target_type || undefined,
      success: filters.success === '' ? undefined : filters.success === 'true',
      created_from: filters.created_from ? new Date(filters.created_from).toISOString() : undefined,
      created_to: filters.created_to ? new Date(filters.created_to).toISOString() : undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = result.items
    total.value = result.total
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取审计日志')
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  void refresh()
}

function changePage(next: number) {
  page.value = next
  void refresh()
}

function detailText(item: AuditLogRecord): string {
  try {
    return JSON.stringify(item.detail ?? {})
  } catch {
    return '{}'
  }
}

onMounted(refresh)
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">SYSTEM · AUDIT</p>
      <h1>审计日志</h1>
      <p>记录登录、账号、文档、助手、外部模型与 Harness 等敏感操作，成功与失败都会保留。</p>
    </header>
    <section class="library-panel">
      <div class="section-heading">
        <div><p class="eyebrow">AUDIT</p><h2>操作记录 <span>{{ total }}</span></h2></div>
      </div>
      <div class="filter-row">
        <input v-model="filters.username" placeholder="操作用户">
        <input v-model="filters.action" placeholder="操作类型，如 login_success">
        <input v-model="filters.target_type" placeholder="目标类型，如 document">
        <select v-model="filters.success">
          <option value="">全部结果</option>
          <option value="true">成功</option>
          <option value="false">失败</option>
        </select>
        <input v-model="filters.created_from" type="datetime-local">
        <input v-model="filters.created_to" type="datetime-local">
        <button type="button" class="secondary-action" @click="applyFilters">筛选</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="loading" class="empty">加载中…</p>
      <div v-else class="admin-table-wrap">
        <table class="admin-table">
          <thead><tr><th>时间</th><th>操作用户</th><th>操作类型</th><th>目标类型</th><th>目标</th><th>IP</th><th>结果</th><th>错误码</th><th>详情</th></tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>{{ new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) }}</td>
              <td>{{ item.username || '—' }}</td>
              <td>{{ item.action }}</td>
              <td>{{ item.target_type || '—' }}</td>
              <td class="mono">{{ item.target_id || '—' }}</td>
              <td>{{ item.ip_address || '—' }}</td>
              <td><span :class="item.success ? 'is-active' : 'is-stale'">{{ item.success ? '成功' : '失败' }}</span></td>
              <td>{{ item.error_code || '—' }}</td>
              <td>
                <button type="button" class="link-button" @click="expanded = expanded === item.id ? '' : item.id">查看</button>
                <pre v-if="expanded === item.id" class="audit-detail">{{ detailText(item) }}</pre>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <nav v-if="total > pageSize" class="pagination">
        <button :disabled="page === 1" @click="changePage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
        <button :disabled="page * pageSize >= total" @click="changePage(page + 1)">下一页</button>
      </nav>
    </section>
  </main>
</template>
