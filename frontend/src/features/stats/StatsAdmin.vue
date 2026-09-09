<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError } from '../../api/documents'
import { getStatsOverview, type StatsOverview } from '../../api/stats'

const overview = ref<StatsOverview | null>(null)
const days = ref(7)
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
    overview.value = await getStatsOverview(days.value)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '无法读取统计'
  }
}

function changeDays(next: number) {
  days.value = next
  void refresh()
}

onMounted(refresh)
</script>

<template>
  <main class="app-shell">
    <header class="hero"><p class="eyebrow">OPERATIONS · STATS</p><h1>运营统计</h1><p>汇总问答量、检索性能、模型成功率与员工反馈，帮助发现知识盲区与质量问题。</p></header>
    <section class="library-panel">
      <div class="section-heading">
        <div><p class="eyebrow">OVERVIEW</p><h2>最近 {{ days }} 天</h2></div>
        <nav class="library-modes">
          <button :class="{ active: days === 7 }" @click="changeDays(7)">7 天</button>
          <button :class="{ active: days === 30 }" @click="changeDays(30)">30 天</button>
        </nav>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
      <div v-if="overview" class="metric-grid">
        <div><b>{{ overview.questions_today }}</b><span>今日提问</span></div>
        <div><b>{{ overview.questions }}</b><span>提问总数</span></div>
        <div><b>{{ overview.active_users }}</b><span>活跃用户</span></div>
        <div><b>{{ ms(overview.avg_first_token_ms) }}</b><span>平均首字时间</span></div>
        <div><b>{{ ms(overview.avg_answer_ms) }}</b><span>平均回答时间</span></div>
        <div><b>{{ ms(overview.avg_retrieval_ms) }}</b><span>平均检索耗时</span></div>
        <div><b>{{ pct(overview.local_success_rate) }}</b><span>本地模型成功率</span></div>
        <div><b>{{ pct(overview.deepseek_success_rate) }}</b><span>DeepSeek 成功率</span></div>
        <div><b>{{ overview.no_answer_count }}</b><span>无答案次数</span></div>
        <div><b>{{ overview.feedback.total }}</b><span>反馈总数（{{ overview.feedback.up }} 赞 / {{ overview.feedback.down }} 踩）</span></div>
        <div><b>{{ overview.cache_hits }}</b><span>缓存命中</span></div>
        <div><b>{{ overview.failures.parse_failed + overview.failures.index_failed }}</b><span>解析/索引失败</span></div>
      </div>
    </section>

    <template v-if="overview">
      <div class="stats-columns">
        <section class="library-panel">
          <p class="eyebrow">TOP QUERIES</p>
          <h2 class="stats-title">最常查询的问题</h2>
          <ol v-if="overview.top_queries.length" class="stats-list">
            <li v-for="item in overview.top_queries" :key="item.question"><span>{{ item.question }}</span><em>{{ item.count }} 次</em></li>
          </ol>
          <p v-else class="empty">暂无数据</p>
        </section>
        <section class="library-panel">
          <p class="eyebrow">TOP DOCUMENTS</p>
          <h2 class="stats-title">最常被引用的资料</h2>
          <ol v-if="overview.top_documents.length" class="stats-list">
            <li v-for="item in overview.top_documents" :key="item.document_id"><span>{{ item.document_name }}</span><em>{{ item.count }} 次</em></li>
          </ol>
          <p v-else class="empty">暂无数据</p>
        </section>
      </div>

      <section v-if="overview.no_answer_samples.length" class="library-panel">
        <p class="eyebrow">NO ANSWER</p>
        <h2 class="stats-title">未能回答的问题</h2>
        <ol class="stats-list">
          <li v-for="item in overview.no_answer_samples.slice(0, 5)" :key="item.message_id"><span>{{ item.message_id }}</span><em>{{ new Date(item.created_at).toLocaleDateString('zh-CN') }}</em></li>
        </ol>
      </section>
    </template>
  </main>
</template>
