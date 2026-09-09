<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{ source: string }>()
const emit = defineEmits<{ citation: [number]; open: [string] }>()

const html = computed(() => renderMarkdown(props.source))

function handleClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  const citation = target.closest<HTMLElement>('.citation')
  if (citation) {
    const number = Number(citation.dataset.citation)
    if (number) emit('citation', number)
    return
  }
  const copy = target.closest<HTMLElement>('.code-copy')
  if (copy) {
    const block = copy.closest<HTMLElement>('.code-block')
    const code = block?.querySelector<HTMLElement>('code')
    const text = code?.innerText ?? ''
    if (text && navigator.clipboard) {
      void navigator.clipboard.writeText(text)
      const original = copy.textContent
      copy.textContent = '已复制'
      window.setTimeout(() => { copy.textContent = original }, 1200)
    }
    return
  }
  const link = target.closest<HTMLAnchorElement>('a')
  if (link && link.dataset.documentId) {
    event.preventDefault()
    emit('open', link.dataset.documentId)
  }
}
</script>

<template>
  <div class="markdown" @click="handleClick" v-html="html"></div>
</template>
