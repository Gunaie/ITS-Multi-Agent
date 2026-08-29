<template>
  <el-config-provider>
    <router-view v-if="isLoggedIn" />
    <div v-else class="login-container">
      <el-card class="login-card">
        <template #header>
          <div class="card-header">
            <span>{{ isRegister ? '管理平台注册' : '管理平台登录' }}</span>
          </div>
        </template>
        <el-form :model="authForm" label-position="top">
          <el-form-item label="用户名">
            <el-input v-model="authForm.username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="authForm.password" type="password" placeholder="请输入密码" show-password @keyup.enter="handleAuth" />
          </el-form-item>
          <div class="auth-actions">
            <el-button type="primary" class="auth-btn" :loading="authLoading" @click="handleAuth">
              {{ isRegister ? '注 册' : '登 录' }}
            </el-button>
            <el-button type="text" class="auth-switch" @click="isRegister = !isRegister">
              {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
            </el-button>
          </div>
        </el-form>
      </el-card>
    </div>
  </el-config-provider>
</template>

<script setup>
import { ref } from 'vue'
import { login, register } from '@/api/app'
import { ElMessage } from 'element-plus'

const isLoggedIn = ref(!!localStorage.getItem('token'))
const isRegister = ref(false)
const authLoading = ref(false)
const authForm = ref({
  username: '',
  password: ''
})

const handleAuth = async () => {
  if (!authForm.value.username || !authForm.value.password) {
    ElMessage.warning('请填写完整信息')
    return
  }
  
  authLoading.value = true
  try {
    if (isRegister.value) {
      await register(authForm.value.username, authForm.value.password)
      ElMessage.success('注册成功，正在为您自动登录...')
      const res = await login(authForm.value.username, authForm.value.password)
      localStorage.setItem('token', res.access_token)
      isLoggedIn.value = true
      ElMessage.success('登录成功')
    } else {
      const res = await login(authForm.value.username, authForm.value.password)
      localStorage.setItem('token', res.access_token)
      isLoggedIn.value = true
      ElMessage.success('登录成功')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  } finally {
    authLoading.value = false
  }
}
</script>

<style>
:root {
  /* 明亮科技风配色 - 同步自咨询平台 */
  --sidebar-bg: #F8FAFC;
  --main-bg: #FFFFFF;
  --card-bg: #FFFFFF;
  --primary-green: #10B981;
  --primary-blue: #3B82F6;
  --text-main: #1E293B;
  --text-sub: #64748B;
  --border-color: #E2E8F0;
  --divider-color: #F1F5F9;
  --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  
  /* Element Plus 变量覆盖 */
  --el-menu-bg-color: var(--sidebar-bg);
  --el-menu-hover-bg-color: var(--divider-color);
  --el-menu-text-color: var(--text-sub);
  --el-menu-active-color: var(--primary-blue);
  --el-bg-color: var(--main-bg);
}

html, body {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: 'Inter', 'SF Pro Display', 'PingFang SC', 'Noto Sans SC', sans-serif;
  background-color: var(--main-bg);
  color: var(--text-main);
  -webkit-font-smoothing: antialiased;
}

.login-container {
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background-color: var(--sidebar-bg);
  background-image: radial-gradient(var(--border-color) 1px, transparent 1px);
  background-size: 30px 30px;
}

.login-card {
  width: 400px;
  background-color: var(--card-bg);
  border-color: var(--border-color);
  color: var(--text-main);
  box-shadow: var(--shadow-md);
  border-radius: 12px;
}

.login-card :deep(.el-card__header) {
  border-bottom-color: var(--divider-color);
  text-align: center;
  font-size: 20px;
  font-weight: bold;
}

.login-card :deep(.el-form-item__label) {
  color: var(--text-sub);
}

.auth-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 20px;
}

.auth-btn {
  width: 100%;
  border-radius: 8px;
  height: 40px;
}

.auth-switch {
  color: var(--primary-blue);
}
</style>
