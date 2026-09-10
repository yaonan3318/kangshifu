import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'

// 统一检测会话失效：任意 /api/* 返回 401 时通知应用回到登录页，
// 页面组件保持挂载（v-show），避免丢失未发送的输入草稿。
const originalFetch = window.fetch.bind(window)
window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const response = await originalFetch(input, init)
  if (response.status === 401) {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url
    if (url.includes('/api/')) window.dispatchEvent(new CustomEvent('company-auth-expired'))
  }
  return response
}

createApp(App).mount('#app')
