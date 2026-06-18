<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)"
             title="下载任务配置（评测批次）" width="760px" @open="onOpen">
    <el-alert type="info" :closable="false" style="margin-bottom:12px">
      任务总题集已固定为 <b>{{ totalQids.length }}</b> 题。每次下载生成一个独立批次配置，
      在本机运行后导入即按 (任务,模型,问题) 合并进本任务。
      <b>同一模型可分多次下载不同题区间</b>（如先 1-12，再 13-40），不会覆盖已导入结果。
    </el-alert>

    <div v-for="(row, i) in batchRows" :key="i" class="batch-row">
      <el-select v-model="row.model_key" placeholder="选模型" style="width:170px">
        <el-option v-for="m in readyModels" :key="m.key" :label="m.name" :value="m.key"
                   :disabled="batchRows.some((r,j)=>j!==i&&r.model_key===m.key)" />
      </el-select>

      <div class="range-box">
        <span class="range-hint">题号区间</span>
        <el-input v-model="row.from" placeholder="起" size="small" style="width:60px" />
        <span>-</span>
        <el-input v-model="row.to" placeholder="止" size="small" style="width:60px" />
        <el-button size="small" link type="primary" @click="applyRange(row)">应用</el-button>
        <el-button size="small" link @click="selectAll(row)">全选</el-button>
        <el-button size="small" link @click="row.question_ids=[]">清空</el-button>
        <span class="range-count">已选 {{ row.question_ids.length }}/{{ totalQids.length }}</span>
      </div>
      <el-button type="danger" link @click="batchRows.splice(i,1)">删</el-button>

      <el-select v-model="row.question_ids" multiple collapse-tags collapse-tags-tooltip
                 placeholder="题区间（默认全选总题集）" style="width:100%;margin-top:4px">
        <el-option v-for="qid in totalQids" :key="qid" :label="qid" :value="qid" />
      </el-select>
    </div>

    <el-button size="small" @click="batchRows.push({model_key:'',question_ids:[],from:'',to:''})">
      + 添加模型
    </el-button>

    <el-form-item label="请求间隔" label-width="100px" style="margin-top:12px">
      <el-slider v-model="delay" :min="3" :max="15" :step="1" show-input />
    </el-form-item>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
      <el-button type="success" plain :loading="downloading" @click="downloadBatch(false)">
        下载并继续
      </el-button>
      <el-button type="success" :loading="downloading" @click="downloadBatch(true)">
        下载任务配置
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiFetch } from '../composables/useWebSocket'
import { createBatch } from '../api/tasks'

const props = defineProps({
  visible: Boolean,
  taskId: { type: String, required: true },
  taskName: { type: String, default: 'task' },
  totalQids: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:visible', 'downloaded'])

const readyModels = ref([])
const batchRows = ref([{ model_key: '', question_ids: [], from: '', to: '' }])
const delay = ref(8)
const downloading = ref(false)

async function onOpen() {
  batchRows.value = [{ model_key: '', question_ids: [], from: '', to: '' }]
  delay.value = 8
  if (!readyModels.value.length) await loadModels()
}

async function loadModels() {
  try {
    const [mRes, wsRes] = await Promise.all([
      apiFetch('/settings/models'),
      apiFetch('/webchat/auth/status'),
    ])
    const models = (mRes.data && (mRes.data.models || mRes.data)) || []
    const ws = wsRes.data || {}
    readyModels.value = models.map(m => {
      const w = ws[m.key] || {}
      return { ...m, webchat_status: w.has_auth ? 'ready' : 'no_auth' }
    }).filter(m => m.webchat_status === 'ready')
    if (!readyModels.value.length) {
      ElMessage.warning('暂无已配置登录态的模型，请先在本地运行 setup_webchat_auth.py')
    }
  } catch (e) {
    ElMessage.error(`加载模型失败: ${e.message || e}`)
  }
}

function qnum(qid) {
  const m = String(qid).match(/(\d+)/)
  return m ? parseInt(m[1]) : NaN
}
function applyRange(row) {
  const a = parseInt(row.from), b = parseInt(row.to)
  if (isNaN(a) || isNaN(b) || a > b) return ElMessage.warning('请输入有效起止题号')
  row.question_ids = props.totalQids.filter(qid => {
    const n = qnum(qid)
    return !isNaN(n) && n >= a && n <= b
  })
  if (!row.question_ids.length) ElMessage.warning('该区间未匹配到题目，请检查题号')
}
function selectAll(row) { row.question_ids = [...props.totalQids] }

async function downloadBatch(closeAfter) {
  const rows = batchRows.value.filter(r => r.model_key)
  if (!rows.length) return ElMessage.warning('请至少添加一个模型')
  const per_model = {}
  for (const r of rows) {
    per_model[r.model_key] = r.question_ids.length ? r.question_ids : [...props.totalQids]
  }
  downloading.value = true
  try {
    const res = await createBatch(props.taskId, {
      model_keys: Object.keys(per_model),
      per_model_question_ids: per_model,
      delay: delay.value,
    })
    if (!res?.success) return ElMessage.error(res?.detail || '生成配置失败')
    const cfg = res.data
    const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `task_${props.taskName}_${cfg.batch_id}.json`
    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    ElMessage.success('任务配置已下载，请在本机运行 local_webchat_runner.py --config 该文件')
    emit('downloaded')
    if (closeAfter) {
      emit('update:visible', false)
    } else {
      batchRows.value = [{ model_key: '', question_ids: [], from: '', to: '' }]
    }
  } finally { downloading.value = false }
}
</script>

<style scoped>
.batch-row {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 10px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.range-box { display: flex; align-items: center; gap: 4px; flex: 1; min-width: 320px; }
.range-hint { font-size: 12px; color: #666; }
.range-count { font-size: 12px; color: #999; margin-left: 4px; }
</style>
