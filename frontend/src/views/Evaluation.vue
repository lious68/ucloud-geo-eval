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
      <el-timeline>
        <el-timeline-item v-for="(log, i) in logs" :key="i" :timestamp="log.time" placement="top">
          {{ log.text }}
        </el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
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
      webchat_status = 'stub'  // 暂不支持
    } else if (ws.has_auth && ws.is_valid) {
      webchat_status = 'ready'
    } else if (ws.has_auth) {
      webchat_status = 'ready'  // 有认证文件即可使用，后续评测时再实际验证
    }
    return { ...m, webchat_status }
  })
})

async function loadConfig() {
  try {
    const mRes = await apiFetch('/settings/models')
    const mData = mRes.data || {}
    models.value = mData.models || mData || []

    // 获取品类
    const cRes = await apiFetch('/questions/categories')
    categories.value = cRes.data || []

    // 获取 WebChat 认证状态
    const wsRes = await apiFetch('/webchat/auth/status')
    webchatStatus.value = wsRes.data || {}

    // 根据模式自动勾选可用模型
    onModeChange(form.value.mode)
  } catch (e) {
    console.error('loadConfig error:', e)
  }
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
      } else if (data.type === 'completed') {
        progress.value = 100
        statusText.value = '评测完成！'
        disconnect()
        setTimeout(() => router.push('/dashboard'), 1500)
      } else if (data.type === 'failed') {
        statusText.value = `评测失败: ${data.error}`
        disconnect()
      }
    })
  } catch (e) {
    ElMessage.error(e.message)
    running.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
</style>