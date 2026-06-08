<template>
  <!-- 登录页不显示侧边栏布局 -->
  <template v-if="route.path === '/login'">
    <router-view />
  </template>
  <el-container v-else class="app-container">
    <el-aside width="220px" class="sidebar">
      <div class="logo">
        <span class="logo-icon">🎯</span>
        <span class="logo-text">UCloud GEO</span>
      </div>
      <el-menu :default-active="currentRoute" router class="sidebar-menu">
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/evaluation">
          <el-icon><VideoPlay /></el-icon>
          <span>执行评测</span>
        </el-menu-item>
        <el-menu-item index="/history">
          <el-icon><Clock /></el-icon>
          <span>历史评测情况</span>
        </el-menu-item>
        <el-menu-item index="/citation-sources">
          <el-icon><Link /></el-icon>
          <span>引用源情况</span>
        </el-menu-item>
        <el-menu-item index="/questions">
          <el-icon><Document /></el-icon>
          <span>问题管理</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
      </el-menu>

      <!-- 评测运行状态全局指示器 -->
      <div v-if="evalStore.running" class="eval-indicator" @click="goToEval">
        <div class="eval-indicator-header">
          <span class="eval-indicator-icon">🚀</span>
          <span class="eval-indicator-title">评测运行中</span>
          <el-tag v-if="evalStore.evalMode === 'webchat'" size="small" type="info">🌐</el-tag>
        </div>
        <el-progress :percentage="evalStore.progressPercent" :stroke-width="8"
          :status="evalStore.progressPercent >= 100 ? 'success' : ''"
          style="margin: 6px 0" />
        <div class="eval-indicator-status">{{ evalStore.statusText }}</div>
        <div class="eval-indicator-heartbeat">
          <span :class="evalStore.heartbeatActive ? 'hb-dot active' : (evalStore.heartbeatStalled ? 'hb-dot stalled' : 'hb-dot inactive')"></span>
          <span v-if="evalStore.heartbeatActive" class="hb-text ok">进程活跃</span>
          <span v-else-if="evalStore.heartbeatStalled" class="hb-text warn">⚠️ 可能挂了</span>
          <span v-else class="hb-text wait">等待进度...</span>
          <span class="hb-time">{{ evalStore.lastUpdateTime || '—' }}</span>
        </div>
      </div>

      <div class="sidebar-footer">
        <el-button text style="color:rgba(255,255,255,0.5);width:100%" @click="handleLogout">
          <el-icon><SwitchButton /></el-icon> 退出登录
        </el-button>
      </div>
    </el-aside>
    <el-main class="main-content">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { removeToken, getToken } from './composables/useWebSocket'
import { useEvalProgressStore } from './stores/evalProgress'

const route = useRoute()
const router = useRouter()
const currentRoute = computed(() => route.path)
const evalStore = useEvalProgressStore()

// 页面加载时自动检测是否有运行中的评测，恢复状态（需要登录态）
onMounted(() => {
  if (getToken()) {
    evalStore.recoverRunningEval()
  }
})

function goToEval() {
  router.push('/evaluation')
}

async function handleLogout() {
  const token = getToken()
  if (token) {
    try { await fetch('/api/auth/logout', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } }) } catch (e) {}
  }
  removeToken()
  router.push('/login')
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f0f2f5; }
.app-container { height: 100vh; }
.sidebar { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); overflow-y: auto; display: flex; flex-direction: column; }
.sidebar .logo { padding: 20px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.1); }
.sidebar .logo-icon { font-size: 28px; }
.sidebar .logo-text { color: #fff; font-size: 18px; font-weight: 700; margin-left: 8px; }
.sidebar-menu { border-right: none !important; flex: 1; }
.sidebar .el-menu { background: transparent; }
.sidebar .el-menu-item { color: rgba(255,255,255,0.7); }
.sidebar .el-menu-item:hover { color: #fff; background: rgba(255,255,255,0.1); }
.sidebar .el-menu-item.is-active { color: #fff; background: rgba(15,52,96,0.6); border-right: 3px solid #409eff; }
.sidebar-footer { padding: 12px; border-top: 1px solid rgba(255,255,255,0.1); }
.main-content { padding: 24px; overflow-y: auto; background: #f0f2f5; }
</style>

<style scoped>
/* 评测运行状态全局指示器 */
.eval-indicator {
  margin: 12px 8px;
  padding: 12px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(64,158,255,0.3);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}
.eval-indicator:hover {
  background: rgba(255,255,255,0.14);
}
.eval-indicator-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.eval-indicator-icon { font-size: 16px; }
.eval-indicator-title {
  font-size: 13px;
  font-weight: 600;
  color: #409eff;
}
.eval-indicator-status {
  font-size: 12px;
  color: rgba(255,255,255,0.6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.eval-indicator-heartbeat {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.hb-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.hb-dot.active { background: #10b981; animation: pulse 1.5s ease-in-out infinite; }
.hb-dot.inactive { background: #ef4444; }
.hb-dot.stalled { background: #f56c6c; animation: blink 1s ease-in-out infinite; }
.hb-text { font-size: 12px; }
.hb-text.ok { color: #10b981; }
.hb-text.warn { color: #f56c6c; }
.hb-text.wait { color: rgba(255,255,255,0.5); }
.hb-time { font-size: 11px; color: rgba(255,255,255,0.4); margin-left: 4px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }
</style>