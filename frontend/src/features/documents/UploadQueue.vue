<script setup lang="ts">
import { ref } from 'vue'
import { ApiError, uploadDocument } from '../../api/documents'

type QueueState = 'waiting' | 'uploading' | 'done' | 'failed'
interface QueueItem { id: string; file: File; state: QueueState; progress: number; message: string }

const emit = defineEmits<{ uploaded: [] }>()
const queue = ref<QueueItem[]>([])
const dragging = ref(false)
let running = 0

function addFiles(files: FileList | File[]) {
  for (const file of Array.from(files)) {
    queue.value.push({ id: crypto.randomUUID(), file, state: 'waiting', progress: 0, message: '等待上传' })
  }
  runQueue()
}

function selected(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files) addFiles(input.files)
  input.value = ''
}

function dropped(event: DragEvent) {
  dragging.value = false
  if (event.dataTransfer?.files) addFiles(event.dataTransfer.files)
}

function runQueue() {
  while (running < 2) {
    const item = queue.value.find((entry) => entry.state === 'waiting')
    if (!item) return
    running += 1
    item.state = 'uploading'
    item.message = '正在上传'
    uploadDocument(item.file, ({ loaded, total }) => {
      item.progress = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0
    }).then(() => {
      item.state = 'done'
      item.progress = 100
      item.message = '等待处理'
      emit('uploaded')
    }).catch((error: unknown) => {
      item.state = 'failed'
      item.message = error instanceof ApiError ? error.message : '上传失败'
    }).finally(() => {
      running -= 1
      runQueue()
    })
  }
}
</script>

<template>
  <section class="upload-panel" aria-labelledby="upload-title">
    <div class="section-heading">
      <div><p class="eyebrow">UPLOAD</p><h2 id="upload-title">添加本地资料</h2></div>
      <label class="primary-action">选择文件<input class="visually-hidden" type="file" multiple @change="selected"></label>
    </div>
    <div class="drop-zone" :class="{ active: dragging }" @dragenter.prevent="dragging = true" @dragover.prevent @dragleave.prevent="dragging = false" @drop.prevent="dropped">
      <strong>将文件拖到这里</strong><span>支持 PDF、Office、新文本与图片，单文件最大 200 MB</span>
    </div>
    <ul v-if="queue.length" class="upload-list" aria-live="polite">
      <li v-for="item in queue" :key="item.id">
        <div class="upload-copy"><strong>{{ item.file.name }}</strong><span>{{ item.message }}</span></div>
        <progress :value="item.progress" max="100">{{ item.progress }}%</progress>
      </li>
    </ul>
  </section>
</template>

