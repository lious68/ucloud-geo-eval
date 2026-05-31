import { ref } from 'vue'

const API_BASE = '/api'

// Token 管理
const TOKEN_KEY = 'geo_auth_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken() {
  localStorage.removeItem(TOKEN_KEY)
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
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (res.status === 401) {
    removeToken()
    window.location.href = '/login'
    throw new Error('登录已过期')
  }

  if (!res.ok) throw new Error(`API Error: ${res.status}`)
  return res.json()
}
