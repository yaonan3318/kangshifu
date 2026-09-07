<script setup lang="ts">
import { computed, ref } from 'vue'
import type { HarnessApproval } from '../../types/answer'

const props = defineProps<{ approval: HarnessApproval; busy: boolean }>()
const emit = defineEmits<{ confirm: [value: string]; reject: [] }>()
const confirmation = ref('')
const valid = computed(() => confirmation.value === props.approval.context)
</script>

<template>
  <section class="harness-approval">
    <p class="danger-label">需要人工确认 · Kubernetes 写操作</p>
    <h3>{{ approval.tool_name }}</h3>
    <dl><div><dt>Context</dt><dd>{{ approval.context }}</dd></div><div><dt>Namespace</dt><dd>{{ approval.namespace }}</dd></div><div><dt>目标</dt><dd>{{ approval.target }}</dd></div></dl>
    <details open><summary>预检结果</summary><pre>{{ approval.dry_run_output || '预检完成' }}</pre></details>
    <details v-if="approval.diff_output"><summary>变更差异</summary><pre>{{ approval.diff_output }}</pre></details>
    <details v-if="approval.yaml_content"><summary>部署 YAML</summary><pre>{{ approval.yaml_content }}</pre></details>
    <label>输入 <b>{{ approval.context }}</b> 确认目标集群<input v-model="confirmation" :disabled="busy" autocomplete="off"></label>
    <div class="approval-actions"><button type="button" class="reject" :disabled="busy" @click="emit('reject')">拒绝</button><button type="button" :disabled="busy || !valid" @click="emit('confirm', confirmation)">确认执行</button></div>
  </section>
</template>
