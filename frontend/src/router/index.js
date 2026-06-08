import { createRouter, createWebHistory } from 'vue-router'
import { getToken, removeToken } from '../composables/useWebSocket'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/evaluation', name: 'Evaluation', component: () => import('../views/Evaluation.vue') },
  { path: '/questions', name: 'Questions', component: () => import('../views/Questions.vue') },
  { path: '/history', name: 'History', component: () => import('../views/History.vue') },
  { path: '/citation-sources', name: 'CitationSources', component: () => import('../views/CitationSources.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转登录页（所有非 public 路由都需要登录）
router.beforeEach(async (to, from, next) => {
  if (to.meta.public || to.path === '/login') {
    return next()
  }

  // 无 token → 直接跳登录页
  const token = getToken()
  if (!token) {
    return next('/login')
  }

  // 验证 token 有效性
  try {
    const res = await fetch('/api/auth/check', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    const data = await res.json()
    if (!data.data?.authenticated) {
      removeToken()
      return next('/login')
    }
  } catch (e) {
    // 网络错误不拦截，让页面正常加载
  }

  next()
})

export default router
