<template>
  <div class="task-list">
    <h2 class="page-title">🚀 执行评测（任务 → 模型 → 问题）</h2>

    <el-card>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-weight:600">任务列表</span>
        <el-button v-if="isAdmin()" type="primary" @click="openWizard">
          <el-icon><Plus /></el-icon> 新建任务
        </el-button>
      </div>
      <el-alert type="info" :closable="false" style="margin-bottom:12px">
        一个任务 = 固定总题集。任务建好后，可在<b>任务详情 →「添加批次」</b>里反复追加：
        先下 ds、再下豆包 1-12、再下豆包 13-40、再下 kimi、再下文心……每个批次独立下载配置、本机运行、导入，
        服务器按 (任务,模型,问题) 自动合并去重，并以任务内全部模型×问题为分母重算 GEO。
      </el-alert>
      <el-table :data="tasks" v-loading="loading" stripe>
        <el-table-column prop="name" label="任务名" min-width="160" />
        <el-table-column label="模型">
          <template #default="{ row }">
            <el-tag v-for="m in row.models" :key="m" size="small" style="margin:2px">{{ m }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="题数" width="80">
          <template #default="{ row }">{{ (row.question_ids||[]).length }}</template>
        </el-table-column>
        <el-table-column label="覆盖率" width="160">
          <template #default="{ row }">
            <el-progress :percentage="Math.round((row.coverage_rate||0)*100)" :status="row.coverage_rate>=1?'success':''" />
            <span style="font-size:12px;color:#999">{{ row.done_cells }}/{{ row.total_cells }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status==='active'?'success':'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="$router.push(`/tasks/${row.id}`)">详情</el-button>
            <el-button v-if="isAdmin()" size="small" type="danger" plain @click="onDel(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建任务向导（仅定任务总题集，建完即弹下载配置对话框） -->
    <el-dialog v-model="wizard" title="新建任务" width="560px">
      <el-form label-width="100px">
        <el-form-item label="任务名">
          <el-input v-model="form.name" placeholder="GEO评估" />
        </el-form-item>
        <el-form-item label="品类筛选">
          <el-select v-model="form.categories" multiple placeholder="全部品类（默认全部 48 题）" style="width:100%">
            <el-option v-for="c in categories" :key="c.name" :label="`${c.name} (${c.count})`" :value="c.name" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="totalQids.length" label="总题集">
          <el-tag type="info">已固定 {{ totalQids.length }} 题</el-tag>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="wizard=false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createTaskStep">创建任务</el-button>
      </template>
    </el-dialog>

    <!-- 首批配置下载（复用 TaskDetail 同款对话框） -->
    <BatchDownloadDialog v-model:visible="batchDialog"
      :task-id="createdTaskId"
      :task-name="form.name"
      :total-qids="totalQids"
      @downloaded="load" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch, isAdmin } from '../composables/useWebSocket'
import { listTasks, createTask, deleteTask } from '../api/tasks'
import BatchDownloadDialog from '../components/BatchDownloadDialog.vue'

const tasks = ref([])
const loading = ref(false)
const wizard = ref(false)
const categories = ref([])
const form = ref({ name: 'GEO评估', categories: [] })
const totalQids = ref([])
const createdTaskId = ref('')
const batchDialog = ref(false)
const creating = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await listTasks()
    tasks.value = res.data || []
  } finally { loading.value = false }
}

async function loadCategories() {
  try {
    const cRes = await apiFetch('/questions/categories')
    categories.value = cRes.data || []
  } catch (e) {
    ElMessage.error(`加载品类失败: ${e.message || e}`)
  }
}

async function openWizard() {
  form.value = { name: 'GEO评估', categories: [] }
  totalQids.value = []
  createdTaskId.value = ''
  if (!categories.value.length) await loadCategories()
  wizard.value = true
}

async function createTaskStep() {
  creating.value = true
  try {
    const res = await createTask({
      name: form.value.name,
      categories: form.value.categories.length ? form.value.categories : null,
    })
    if (!res?.success) return ElMessage.error(res?.detail || '建任务失败')
    createdTaskId.value = res.data.id
    totalQids.value = res.data.question_ids || []
    ElMessage.success(`任务已创建，总题集 ${totalQids.value.length} 题`)
    wizard.value = false
    batchDialog.value = true
    await load()
  } finally { creating.value = false }
}

async function onDel(row) {
  await ElMessageBox.confirm(`确定删除任务「${row.name}」及全部结果？`, '删除', { type: 'warning' })
  try {
    const res = await deleteTask(row.id)
    if (!res?.success) return ElMessage.error(res?.detail || '删除失败')
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(`删除失败: ${e.message || e}`)
  }
}

onMounted(async () => { await load(); await loadCategories() })
</script>

<style scoped>
.page-title { font-size: 22px; margin-bottom: 20px; color: #1a1a2e; }
</style>
