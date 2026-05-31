<template>
  <div class="evaluation">
    <h2 class="page-title">🚀 执行评测</h2>

    <!-- 评测配置 -->
    <el-card v-if="!running">
      <el-form :model="form" label-width="100px">
        <el-form-item label="评测名称">
          <el-input v-model="form.name" placeholder="GEO评估" />
        </el-form-item>
        <el-form-item label="选择模型">
          <el-checkbox-group v-model="form.model_keys">
            <el-checkbox v-for="m in models" :key="m.key" :label="m.key">{{ m.name }}
              <el-tag v-if="!m.has_api_key" type="danger" size="small" style="margin-left:4px">未配置</el-tag>
              <el-tag v-if="m.has_api_key" type="success" size="small" style="margin-left:4px">✓</el-tag>
            </el-checkbox>
          </el-checkbox-group>
          <div v-if="!models.some(m => m.has_api_key)" style="margin-top:8px">
            <el-alert type="warning" :closable="false" show-icon>
              所有模型均未配置 API Key，请先到「系统设置」配置 API Key 或启用 ModelVerse 中转
            </el-alert>
          </div>
        </el-form-item>
        <el-form-item label="品类筛选">
          <el-select v-model="form.categories" multiple placeholder="全部品类" style="width:100%">
            <el-option v-for="c in categories" :key="c.name" :label="`${c.name} (${c.count})`" :value="c.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="请求间隔">
          <el-slider v-model="form.delay" :min="0" :max="5" :step="0.5" show-input />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="startEval" :disabled="!form.model_keys.length">
            <el-icon><VideoPlay /></el-icon> 开始评测
          </el-button>
          <span v-if="!form.model_keys.length" style="margin-left:12px;color:#999">请至少选择一个已配置的模型</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 进度显示 -->
    <el-card v-if="running">
      <div style="text-align:center;margin-bottom:20px">
        <el-progress type="circle" :percentage="progress" :width="120" />
        <div style="margin-top:12px;font-size:16px">{{ statusText }}</div>
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { apiFetch, useWebSocket } from '../composables/useWebSocket'

const router = useRouter()
const { connect, disconnect } = useWebSocket()

const models = ref([])
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
})

async function loadConfig() {
  try {
    // 获取模型配置 - 适配新的返回格式
    const mRes = await apiFetch('/settings/models')
    const mData = mRes.data || {}
    models.value = mData.models || mData || []
    // 自动勾选已配置API Key的模型
    form.value.model_keys = models.value.filter(m => m.has_api_key).map(m => m.key)

    // 获取品类（公开接口）
    const cRes = await apiFetch('/questions/categories')
    categories.value = cRes.data || []
  } catch (e) {
    console.error('loadConfig error:', e)
  }
}

async function startEval() {
  // 过滤掉没有API Key的模型
  const availableKeys = models.value.filter(m => m.has_api_key).map(m => m.key)
  const selectedAvailable = form.value.model_keys.filter(k => availableKeys.includes(k))

  if (!selectedAvailable.length) {
    ElMessage.warning('请选择至少一个已配置API Key的模型')
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
