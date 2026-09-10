<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { getDashboard, type DashboardStats } from '../../api/stats'

const data = ref<DashboardStats | null>(null)
const error = ref('')

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(0)}%`
}

function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`
}

async function refresh() {
  error.value = ''
  try {
    data.value = await getDashboard()
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '无法读取首页数据'
  }
}

onMounted(refresh)
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">KNOWLEDGE WORKBENCH</p>
      <h1>康师傅知识助手</h1>
      <p>本地部署的企业知识库与 RAG 问答平台：安全上传、混合检索、引用可追溯、反馈驱动优化。</p>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <template v-if="data">
      <section class="library-panel">
        <div class="section-heading"><div><p class="eyebrow">OVERVIEW</p><h2>知识资产</h2></div></div>
        <div class="metric-grid">
          <div><b>{{ data.knowledge_base_count }}</b><span>知识库数量</span></div>
          <div><b>{{ data.document_count }}</b><span>文档数量</span></div>
          <div><b>{{ data.chunk_count }}</b><span>可检索片段</span></div>
          <div><b>{{ data.questions_today }}</b><span>今日问答</span></div>
        </div>
      </section>
      <section class="library-panel">
        <div class="section-heading"><div><p class="eyebrow">QUALITY</p><h2>运行质量（近 30 天）</h2></div></div>
        <div class="metric-grid">
          <div><b>{{ ms(data.avg_response_ms) }}</b><span>平均响应时间</span></div>
          <div><b>{{ pct(data.citation_coverage) }}</b><span>引用覆盖率</span></div>
          <div><b>{{ pct(data.satisfaction) }}</b><span>用户满意度</span></div>
          <div><b>{{ data.knowledge_gap_count }}</b><span>知识缺口数量</span></div>
        </div>
      </section>
      <div class="stats-columns">
        <section class="library-panel">
          <p class="eyebrow">HOT QUESTIONS</p>
          <h2 class="stats-title">热门问题</h2>
          <ol v-if="data.hot_questions.length" class="stats-list">
            <li v-for="item in data.hot_questions" :key="item.question"><span>{{ item.question }}</span><em>{{ item.count }} 次</em></li>
          </ol>
          <p v-else class="empty">暂无数据</p>
        </section>
        <section class="library-panel">
          <p class="eyebrow">FEEDBACK</p>
          <h2 class="stats-title">用户反馈</h2>
          <div class="metric-grid">
            <div><b>{{ data.feedback.total }}</b><span>反馈总数</span></div>
            <div><b>{{ data.feedback.up }}</b><span>有帮助</span></div>
            <div><b>{{ data.feedback.down }}</b><span>没帮助</span></div>
          </div>
        </section>
      </div>
    </template>
  </main>
</template>
