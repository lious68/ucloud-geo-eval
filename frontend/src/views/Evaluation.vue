<template>
  <div class="evaluation">
    <h2 class="page-title">🚀 执行评测</h2>

    <!-- 评测配置 -->
    <el-card v-if="!running">
      <el-form :model="form" label-width="100px">
        <el-form-item label="评测名称">
          <el-input v-model="form.name" placeholder="GEO评估" />
        </el-form-item>

        <el-form-item label="评测模式">
          <el-radio-group v-model="form.mode" @change="onModeChange">
            <el-radio value="api">API 模式（纯文本生成）</el-radio>
            <el-radio value="webchat">🌐 WebChat 模式（联网搜索）</el-radio>
          </el-radio-group>
          <el-alert v-if="form.mode === 'webchat'" type="info" :closable="false" style="margin-top:8px">
            WebChat 模式通过浏览器自动化模拟真实用户在各 AI 官网提问，模型会联网搜索并引用真实来源。需先在「系统设置」配置各网站的登录状态。
          </el-alert>
        </el-form-item>

        <el-form-item label="选择模型">
          <el-checkbox-group v-model="form.model_keys">
            <el-checkbox v-for="m in displayModels" :key="m.key" :label="m.key">
              {{ m.name }}
              <el-tag v-if="form.mode === 'api'" :type="m.has_api_key ? 'success' : 'danger'" size="small" style="margin-left:4px">
                {{ m.has_api_key ? '✓ API' : '未配置' }}
              </el-tag>
              <el-tag v-if="form.mode === 'webchat'" :type="m.webchat_status === 'ready' ? 'success' : (m.webchat_status === 'no_auth' ? 'danger' : 'warning')" size="small" style="margin-left:4px">
                {{ m.webchat_status === 'ready' ? '✓ 已登录' : (m.webchat_status === 'no_auth' ? '未登录' : m.webchat_status === 'stub' ? '暂不支持' : '已过期') }}
              </el-tag>
            </el-checkbox>
          </el-checkbox-group>
          <div v-if="form.mode === 'api' && !displayModels.some(m => m.has_api_key)" style="margin-top:8px">
            <el-alert type="warning" :closable="false" show-icon>
              所有模型均未配置 API Key，请先到「系统设置」配置 API Key 或启用 ModelVerse 中转
            </el-alert>
          </div>
          <div v-if="form.mode === 'webchat' && !displayModels.some(m => m.webchat_status === 'ready')" style="margin-top:8px">
            <el-alert type="warning" :closable="false" show-icon>
              没有已登录的 WebChat 模型，请先到「系统设置」上传各网站的登录状态文件
            </el-alert>
          </div>
        </el-form-item>

        <el-form-item label="品类筛选">
          <el-select v-model="form.categories" multiple placeholder="全部品类" style="width:100%">
            <el-option v-for="c in categories" :key="c.name" :label="`${c.name} (${c.count})`" :value="c.name" />
          </el-select>
        </el-form-item>

        <el-form-item v-if="form.mode === 'api'" label="请求间隔">
          <el-slider v-model="form.delay" :min="0" :max="5" :step="0.5" show-input />
        </el-form-item>
        <el-form-item v-if="form.mode === 'webchat'" label="请求间隔">
          <el-slider v-model="form.delay" :min="3" :max="15" :step="1" show-input />
          <span style="color:#999;font-size:12px">WebChat 模式建议 8 秒以上，避免被网站限速</span>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="startEval" :disabled="!form.model_keys.length || !canStart">
            <el-icon><VideoPlay /></el-icon> 开始评测
          </el-button>
          <span v-if="!canStart" style="margin-left:12px;color:#999">
            {{ form.mode === 'api' ? '请至少选择一个已配置 API Key 的模型' : '请至少选择一个已登录的 WebChat 模型' }}
          </span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 进度显示 -->
    <el-card v-if="running">
      <div style="text-align:center;margin-bottom:20px">
        <el-progress type="circle" :percentage="progress" :width="120" />
        <div style="margin-top:12px;font-size:16px">{{ statusText }}</div>
        <el-tag v-if="form.mode === 'webchat'" type="info" style="margin-top:8px">🌐 WebChat 模式</el-tag>
      </div>

      <!-- 活跃状态心跳指示器 -->
      <div class="heartbeat-row">
        <span :class="heartbeatActive ? 'heartbeat-dot active' : 'heartbeat-dot inactive'"></span>
        <span v-if="heartbeatActive" style="color:#10b981;font-size:13px">进程活跃 · 正在执行中</span>
        <span v-else style="color:#ef4444;font-size:13px">
          {{ heartbeatStalled ? '⚠️ 进程可能挂了 · 已超过120秒无更新' : '等待首次进度...' }}
        </span>
        <span style="color:#999;font-size:12px;margin-left:12px">上次更新: {{ lastUpdateTime || '—' }}</span>
        <el-button v-if="heartbeatStalled" size="small" type="warning" style="margin-left:8px" @click="checkStatus">
          检查状态
        </el-button>
      </div>

      <el-timeline style="margin-top:16px">
        <el-timeline-item v-for="(log, i) in logs" :key="i" :timestamp="log.time" placement="top">
          {{ log.text }}
        </el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiFetch, useWebSocket } from '../composables/useWebSocket'

const router = useRouter()
const { connect, disconnect } = useWebSocket()

const models = ref([])
const webchatStatus = ref({})
const categories = ref([])
const running = ref(false)
const progress = ref(0)
const statusText = ref('')
const logs = ref([])
const runId = ref('')
const lastUpdateTime = ref('')
const heartbeatActive = ref(false)
const heartbeatStalled = ref(false)
let heartbeatTimer = null

const form = ref({
  name: 'GEO评估',
  model_keys: [],
  categories: [],
  delay: 1.0,
  mode: 'api',
})

const canStart = computed(() => {
  if (form.value.mode === 'api') {
    return form.value.model_keys.some(k => models.value.find(m => m.key === k)?.has_api_key)
  } else {
    return form.value.model_keys.some(k => displayModels.value.find(m => m.key === k)?.webchat_status === 'ready')
  }
})

const displayModels = computed(() => {
  return models.value.map(m => {
    const ws = webchatStatus.value[m.key] || {}
    let webchat_status = 'no_auth'
    if (m.key !== 'kimi' && m.key !== 'deepseek') {
      webchat_status = 'stub'
    } else if (ws.has_auth && ws.is_valid) {
      webchat_status = 'ready'
    } else if (ws.has_auth) {
      webchat_status = 'ready'
    }
    return { ...m, webchat_status }
  })
})

async function loadConfig() {
  try {
    const mRes = await apiFetch('/settings/models')
    const mData = mRes.data || {}
    models.value = mData.models || mData || []

    const cRes = await apiFetch('/questions/categories')
    categories.value = cRes.data || []

    const wsRes = await apiFetch('/webchat/auth/status')
    webchatStatus.value = wsRes.data || {}

    onModeChange(form.value.mode)
  } catch (e) { console.error('loadConfig error:', e) }
}

function onModeChange(mode) {
  if (mode === 'api') {
    form.value.delay = 1.0
    form.value.model_keys = models.value.filter(m => m.has_api_key).map(m => m.key)
  } else {
    form.value.delay = 8
    form.value.model_keys = displayModels.value.filter(m => m.webchat_status === 'ready').map(m => m.key)
  }
}

// 心跳检测：每30秒检查是否收到过进度更新
function startHeartbeat() {
  heartbeatActive.value = false
  heartbeatStalled.value = false
  let secondsSinceUpdate = 0

  heartbeatTimer = setInterval(() => {
    if (lastUpdateTime.value) {
      secondsSinceUpdate += 30
    } else {
      secondsSinceUpdate += 30
    }

    if (secondsSinceUpdate > 120) {
      heartbeatActive.value = false
      heartbeatStalled.value = true
    }
  }, 30000)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

function onProgressReceived() {
  heartbeatActive.value = true
  heartbeatStalled.value = false
  lastUpdateTime.value = new Date().toLocaleTimeString()
}

async function checkStatus() {
  try {
    const res = await apiFetch(`/evaluations/${runId.value}`)
    const run = res.data
    if (run.status === 'completed') {
      progress.value = 100
      statusText.value = '评测已完成'
      heartbeatActive.value = false
      heartbeatStalled.value = false
      stopHeartbeat()
      disconnect()
      setTimeout(() => router.push('/dashboard'), 1500)
    } else if (run.status === 'failed') {
      statusText.value = `评测失败`
      heartbeatActive.value = false
      heartbeatStalled.value = false
      stopHeartbeat()
      disconnect()
    } else if (run.status === 'running') {
      heartbeatActive.value = true
      heartbeatStalled.value = false
      ElMessage.info(`评测仍在运行，已完成 ${run.completed_questions}/${run.total_questions} 题`)
    } else {
      ElMessage.info(`评测状态: ${run.status}`)
    }
  } catch (e) {
    ElMessage.error('无法获取评测状态: ' + e.message)
  }
}

async function startEval() {
  let selectedAvailable
  if (form.value.mode === 'api') {
    const availableKeys = models.value.filter(m => m.has_api_key).map(m => m.key)
    selectedAvailable = form.value.model_keys.filter(k => availableKeys.includes(k))
  } else {
    selectedAvailable = form.value.model_keys.filter(k =>
      displayModels.value.find(m => m.key === k)?.webchat_status === 'ready'
    )
  }

  if (!selectedAvailable.length) {
    ElMessage.warning(form.value.mode === 'api'
      ? '请选择至少一个已配置API Key的模型'
      : '请选择至少一个已登录的WebChat模型')
    return
  }

  try {
    running.value = true
    logs.value = []
    progress.value = 0
    statusText.value = '正在启动评测...'
    lastUpdateTime.value = ''
    startHeartbeat()

    const res = await apiFetch('/evaluations', {
      method: 'POST',
      body: JSON.stringify({
        name: form.value.name,
        model_keys: selectedAvailable,
        categories: form.value.categories.length ? form.value.categories : null,
        delay: form.value.delay,
        mode: form.value.mode,
      }),
    })
    runId.value = res.data.run_id

    connect(runId.value, (data) => {
      if (data.type === 'progress') {
        progress.value = Math.round(data.completed / data.total * 100)
        statusText.value = `${data.current_model} - ${data.current_question}`
        logs.value.unshift({ time: new Date().toLocaleTimeString(), text: `${data.current_model} → ${data.current_question} (${data.completed}/${data.total})` })
        onProgressReceived()
      } else if (data.type === 'completed') {
        progress.value = 100
        statusText.value = '评测完成！'
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnect()
        setTimeout(() => router.push('/dashboard'), 1500)
      } else if (data.type === 'failed') {
        statusText.value = `评测失败: ${data.error}`
        heartbeatActive.value = false
        heartbeatStalled.value = false
        stopHeartbeat()
        disconnect()
      }
    })
  } catch (e) {
    ElMessage.error(e.message)
    running.value = false
    stopHeartbeat()
  }
}

onMounted(loadConfig)
onUnmounted(stopHeartbeat)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
.heartbeat-row { display: flex; align-items: center; gap: 8px; padding: 8px 0; }
.heartbeat-dot { width: 10px; height: 10px; border-radius: 50%; }
.heartbeat-dot.active { background: #10b981; animation: pulse 1.5s ease-in-out infinite; }
.heartbeat-dot.inactive { background: #ef4444; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>