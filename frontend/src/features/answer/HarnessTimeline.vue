<script setup lang="ts">
import type { HarnessStep } from '../../types/answer'
defineProps<{ steps: HarnessStep[] }>()

type ResultRecord = Record<string, unknown>

const statusLabels: Record<HarnessStep['status'], string> = {
  requested: '等待执行',
  running: '正在执行',
  succeeded: '执行完成',
  failed: '执行失败',
  awaiting: '等待确认',
}

function resultSummary(result?: ResultRecord): string {
  if (!result) return ''
  if (typeof result.summary === 'string') return result.summary
  if (typeof result.error === 'string') return result.error
  return '工具已返回结果'
}

function resultItems(result?: ResultRecord): ResultRecord[] {
  if (!result || !Array.isArray(result.data)) return []
  return result.data.filter((item): item is ResultRecord => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
}

function field(item: ResultRecord, key: string): string {
  const value = item[key]
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function location(item: ResultRecord): string {
  const parts = [
    field(item, 'page') && `第 ${field(item, 'page')} 页`,
    field(item, 'slide') && `幻灯片 ${field(item, 'slide')}`,
    field(item, 'sheet') && `工作表 ${field(item, 'sheet')}`,
    field(item, 'sequence') && `片段 ${field(item, 'sequence')}`,
  ]
  return parts.filter(Boolean).join(' · ')
}
</script>

<template>
  <section v-if="steps.length" class="harness-timeline">
    <header><b>Harness 执行过程</b><span>{{ steps.length }} 个步骤</span></header>
    <ol>
      <li v-for="step in steps" :key="step.number" :class="`is-${step.status}`">
        <span class="step-dot"></span>
        <div class="harness-step-body">
          <div class="harness-step-heading">
            <b>{{ step.tool }}</b>
            <span>{{ statusLabels[step.status] }}</span>
          </div>
          <small v-if="step.reason">{{ step.reason }}</small>
          <p v-if="step.result" class="harness-result-summary">{{ resultSummary(step.result) }}</p>

          <details v-if="resultItems(step.result).length" class="harness-result-details">
            <summary>查看资料片段（{{ resultItems(step.result).length }}）</summary>
            <div class="harness-result-list">
              <article v-for="(item, index) in resultItems(step.result)" :key="field(item, 'chunk_id') || index">
                <header>
                  <b>{{ field(item, 'document') || `结果 ${index + 1}` }}</b>
                  <span v-if="location(item)">{{ location(item) }}</span>
                </header>
                <pre v-if="field(item, 'content')">{{ field(item, 'content') }}</pre>
              </article>
            </div>
          </details>

          <details v-if="step.result" class="harness-raw-result">
            <summary>查看原始数据</summary>
            <pre>{{ JSON.stringify(step.result, null, 2) }}</pre>
          </details>
        </div>
      </li>
    </ol>
  </section>
</template>
