<script setup lang="ts">
import type { HarnessStep } from '../../types/answer'
defineProps<{ steps: HarnessStep[] }>()
</script>

<template>
  <section v-if="steps.length" class="harness-timeline">
    <header><b>Harness 执行过程</b><span>{{ steps.length }} 个步骤</span></header>
    <ol>
      <li v-for="step in steps" :key="step.number" :class="`is-${step.status}`">
        <span class="step-dot"></span>
        <div><b>{{ step.tool }}</b><small>{{ step.reason || step.status }}</small>
          <details v-if="step.result"><summary>查看结果</summary><pre>{{ JSON.stringify(step.result, null, 2) }}</pre></details>
        </div>
      </li>
    </ol>
  </section>
</template>
