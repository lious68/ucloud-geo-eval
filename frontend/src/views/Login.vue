<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <span class="logo-icon">🎯</span>
        <h2>UCloud GEO 评估系统</h2>
        <p v-if="isFirstLogin" style="color:#e6a23c;font-size:13px;margin-top:8px">首次使用，请设置管理密码</p>
      </div>
      <el-form @submit.prevent="handleLogin">
        <el-form-item>
          <el-input v-model="password" :type="showPwd ? 'text' : 'password'"
            :placeholder="isFirstLogin ? '设置管理密码（至少6位）' : '请输入管理密码'" size="large"
            @keyup.enter="handleLogin">
            <template #suffix>
              <el-button link @click="showPwd = !showPwd">
                <el-icon><component :is="showPwd ? 'Hide' : 'View'" /></el-icon>
              </el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item v-if="isFirstLogin">
          <el-input v-model="confirmPassword" type="password" placeholder="确认密码" size="large"
            @keyup.enter="handleLogin" />
        </el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="loading" @click="handleLogin">
          {{ isFirstLogin ? '设置密码并登录' : '登 录' }}
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { setToken } from '../composables/useWebSocket'

const router = useRouter()
const password = ref('')
const confirmPassword = ref('')
const showPwd = ref(false)
const loading = ref(false)
const isFirstLogin = ref(false)

onMounted(async () => {
  try {
    const res = await fetch('/api/auth/check')
    const data = await res.json()
    isFirstLogin.value = !data.data?.has_password
    // 已登录直接跳转
    if (data.data?.authenticated) router.push('/dashboard')
  } catch (e) { /* ignore */ }
})

async function handleLogin() {
  if (!password.value) return ElMessage.warning('请输入密码')
  if (isFirstLogin.value && password.value !== confirmPassword.value) return ElMessage.warning('两次密码不一致')
  if (isFirstLogin.value && password.value.length < 6) return ElMessage.warning('密码至少6位')

  loading.value = true
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password.value }),
    })
    const data = await res.json()
    if (data.success) {
      setToken(data.data.token)
      ElMessage.success(isFirstLogin.value ? '密码设置成功' : '登录成功')
      router.push('/dashboard')
    } else {
      ElMessage.error(data.detail || '登录失败')
    }
  } catch (e) {
    ElMessage.error('网络错误')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page { display: flex; justify-content: center; align-items: center; min-height: 100vh; background: linear-gradient(135deg, #1a1a2e 0%, #0f3460 100%); }
.login-card { background: #fff; border-radius: 16px; padding: 40px; width: 400px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
.login-header { text-align: center; margin-bottom: 30px; }
.login-header .logo-icon { font-size: 48px; }
.login-header h2 { color: #1a1a2e; margin-top: 12px; }
</style>
