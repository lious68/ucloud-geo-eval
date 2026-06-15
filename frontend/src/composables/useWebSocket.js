import { ref } from 'vue'
import router from '../router'

const API_BASE = '/api'

// Token 管理
const TOKEN_KEY = 'geo_auth_token'
const ROLE_KEY = 'geo_auth_role'
const USERNAME_KEY = 'geo_auth_username'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ROLE_KEY)
  localStorage.removeItem(USERNAME_KEY)
}

export function getRole() {
  return localStorage.getItem(ROLE_KEY) || 'viewer'
}

export function setRole(role) {
  localStorage.setItem(ROLE_KEY, role)
}

export function getUsername() {
  return localStorage.getItem(USERNAME_KEY) || ''
}

export function setUsername(username) {
  localStorage.setItem(USERNAME_KEY, username)
}

export function isAdmin() {
  return getRole() === 'admin'
}

export function useWebSocket() {
  const ws = ref(null)
  const connected = ref(false)

  function connect(runId, onMessage) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/api/evaluations/ws/${runId}`
    ws.value = new WebSocket(url)
    ws.value.onopen = () => { connected.value = true }
    ws.value.onmessage = (e) => { onMessage(JSON.parse(e.data)) }
    ws.value.onclose = () => { connected.value = false }
    ws.value.onerror = () => { connected.value = false }
  }

  function disconnect() {
    if (ws.value) ws.value.close()
  }

  return { connect, disconnect, connected }
}

export async function apiFetch(path, options = {}) {
  const token = getToken()
  // FormData 上传时不能设置 Content-Type，让浏览器自动设 multipart
  const isFormData = options.body instanceof FormData
  const headers = isFormData
    ? { ...(options.headers || {}), ...(token ? { 'Authorization': `Bearer ${token}` } : {}) }
    : { 'Content-Type': 'application/json', ...options.headers, ...(token ? { 'Authorization': `Bearer ${token}` } : {}) }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (res.status === 401) {
    removeToken()
    router.push('/login')
    throw new Error('登录已过期')
  }

  if (res.status === 403) {
    throw new Error('权限不足，需要管理员权限')
  }

  if (res.status === 413) {
    throw new Error('文件过大，请缩减后重试（上限 50MB）')
  }

  if (!res.ok) {
    // 尝试从响应中提取错误信息，避免解析 HTML 报错
    try {
      const errData = await res.json()
      throw new Error(errData.detail || errData.message || `请求失败 (${res.status})`)
    } catch {
      throw new Error(`请求失败 (${res.status})`)
    }
  }

  return res.json()
}
