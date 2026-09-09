<script setup lang="ts">
import { reactive, ref } from 'vue'
import { AuthError, loginRequest } from '../api/auth'

const emit = defineEmits<{ login: [] }>()
const form = reactive({ username: 'admin', password: '' })
const busy = ref(false)
const error = ref('')

async function submit() {
  if (!form.username.trim() || !form.password || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const state = await loginRequest(form.username.trim(), form.password)
    if (state.authenticated) emit('login')
    else error.value = '登录失败，请重试'
  } catch (reason) {
    error.value = reason instanceof AuthError ? reason.message : '无法连接本地服务'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login-shell">
    <section class="login-panel">
      <span class="login-avatar">康</span>
      <h1>康师傅公司知识助手</h1>
      <p>本地知识库需要登录后才能访问。资料只保存在这台 Mac 上。</p>
      <form class="login-form" @submit.prevent="submit">
        <label>用户名<input v-model="form.username" autocomplete="username" maxlength="255"></label>
        <label>密码<input v-model="form.password" type="password" autocomplete="current-password" maxlength="255"></label>
        <p v-if="error" class="error">{{ error }}</p>
        <button type="submit" :disabled="busy || !form.username.trim() || !form.password">{{ busy ? '登录中…' : '登录' }}</button>
      </form>
      <small>首次使用默认账号 admin / admin123，请在管理员界面中尽快修改。</small>
    </section>
  </main>
</template>
