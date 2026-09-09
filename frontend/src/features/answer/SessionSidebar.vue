<script setup lang="ts">
import { ref } from 'vue'
import type { ChatSessionItem } from '../../types/chat'
import { relativeTime } from '../../utils/time'

const props = defineProps<{
  items: ChatSessionItem[]
  activeId: string | null
  showArchived: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  create: []
  rename: [id: string, title: string]
  archive: [id: string]
  restore: [id: string]
  purge: [id: string]
  search: [value: string]
  toggleArchived: [show: boolean]
}>()

const searchText = ref('')
const editing = ref('')
const renameValue = ref('')

function onSearchInput(event: Event) {
  searchText.value = (event.target as HTMLInputElement).value
  emit('search', searchText.value)
}

function startRename(item: ChatSessionItem) {
  editing.value = item.id
  renameValue.value = item.title
}

function commitRename() {
  if (editing.value && renameValue.value.trim()) emit('rename', editing.value, renameValue.value.trim())
  editing.value = ''
}

function archiveItem(item: ChatSessionItem) {
  if (!window.confirm(`确定归档“${item.title}”？归档后数据仍然保留，可随时恢复。`)) return
  emit('archive', item.id)
}

function restoreItem(item: ChatSessionItem) {
  emit('restore', item.id)
}

function purgeItem(item: ChatSessionItem) {
  if (!window.confirm(`确定永久删除会话“${item.title}”？此操作不可恢复。`)) return
  emit('purge', item.id)
}
</script>

<template>
  <aside class="qa-sidebar">
    <header class="qa-sidebar-head">
      <div>
        <p class="eyebrow">CONVERSATIONS</p>
        <h2>历史会话</h2>
      </div>
      <button type="button" class="new-chat-button" title="新建会话" @click="emit('create')">＋</button>
    </header>

    <div class="qa-sidebar-tools">
      <label class="session-search">
        <input v-model="searchText" type="search" placeholder="搜索历史会话…" @input="onSearchInput">
      </label>
      <div class="session-modes">
        <button :class="{ active: !props.showArchived }" type="button" @click="emit('toggleArchived', false)">会话</button>
        <button :class="{ active: props.showArchived }" type="button" @click="emit('toggleArchived', true)">归档</button>
      </div>
    </div>

    <div class="qa-session-list">
      <p v-if="props.loading" class="qa-sidebar-hint">正在加载…</p>
      <p v-else-if="!props.items.length" class="qa-sidebar-hint">{{ props.showArchived ? '没有归档会话' : '还没有会话，点击 ＋ 开始提问' }}</p>
      <article
        v-for="item in props.items"
        :key="item.id"
        class="session-item"
        :class="{ active: item.id === props.activeId }"
      >
        <button type="button" class="session-open" @click="emit('select', item.id)">
          <template v-if="editing === item.id">
            <input
              v-model="renameValue"
              class="session-rename-input"
              autofocus
              @click.stop
              @keydown.enter.prevent="commitRename"
              @keydown.esc="editing = ''"
              @blur="commitRename"
            >
          </template>
          <template v-else>
            <strong>{{ item.title }}</strong>
            <span v-if="item.last_preview" class="session-preview">{{ item.last_preview }}</span>
            <small>{{ relativeTime(item.updated_at) }} · {{ item.message_count }} 条消息</small>
          </template>
        </button>
        <div class="session-actions">
          <button v-if="editing !== item.id" type="button" title="重命名" @click.stop="startRename(item)">改名</button>
          <template v-if="props.showArchived">
            <button type="button" title="恢复" @click.stop="restoreItem(item)">恢复</button>
            <button type="button" class="danger" title="永久删除" @click.stop="purgeItem(item)">删除</button>
          </template>
          <button v-else type="button" class="danger" title="归档" @click.stop="archiveItem(item)">归档</button>
        </div>
      </article>
    </div>

    <footer class="qa-sidebar-foot">
      <small>会话保存在本机数据库，切换页面或重启后仍可恢复。</small>
    </footer>
  </aside>
</template>
