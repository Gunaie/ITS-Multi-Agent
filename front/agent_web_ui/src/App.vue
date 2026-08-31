<template>
  <el-config-provider namespace="el">
    <div class="app-wrapper">
      <!-- 左侧边栏 -->
      <aside class="app-sidebar">
        <div class="logo-area">
          <div class="logo-box">联想</div>
          <div class="logo-info">
            <span class="logo-text">联想智能技术助手</span>
            <span class="logo-desc">售后技术支持与服务中心</span>
          </div>
        </div>
        
        <el-button class="new-chat-btn" plain @click="handleNewChat">
          <el-icon><Plus /></el-icon>
          <span>新建对话</span>
          <span class="shortcut">Ctrl+K</span>
        </el-button>
        
        <nav class="sidebar-menu">
          <button class="menu-item" type="button" :class="{ active: currentPath === '/chat' && !pendingQuestion }" @click="goSmartConsult">
            <el-icon><ChatDotRound /></el-icon>
            <span>智能咨询</span>
          </button>
          <button class="menu-item" type="button" @click="goServiceStation">
            <el-icon><Location /></el-icon>
            <span>服务站查询</span>
          </button>
          <button class="menu-item" type="button" @click="goWebSearch">
            <el-icon><Connection /></el-icon>
            <span>联网搜索</span>
          </button>
          <button class="menu-item" type="button" @click="handleGoToKnowledge">
            <el-icon><Management /></el-icon>
            <span>知识库管理</span>
            <el-icon class="external-icon"><TopRight /></el-icon>
          </button>
        </nav>
        
        <div class="sidebar-footer">
          <div class="history-title">历史记录</div>
          <div class="session-list">
            <div v-if="sessionList.length === 0" class="history-empty">暂无最近对话</div>
            <div 
              v-for="session in sessionList" 
              :key="session.id" 
              class="session-item"
              :class="{ active: currentSessionId === session.id }"
            >
              <div class="session-item-main" @click="handleSessionClick(session.id)">
                <el-icon class="session-icon"><ChatLineRound /></el-icon>
                
                <div v-if="editingId === session.id" class="session-edit-box" @click.stop>
                  <el-input 
                    v-model="editingTitle" 
                    size="small" 
                    ref="editInput"
                    @blur="submitEdit"
                    @keyup.enter="submitEdit"
                    @keyup.esc="cancelEdit"
                  />
                </div>
                <span v-else class="session-title">{{ session.title }}</span>
              </div>

              <div class="session-ops" @click.stop>
                <el-icon class="op-icon" @click="startEdit(session)"><Edit /></el-icon>
                <el-popconfirm title="确定要删除这段对话吗？" @confirm="handleDelete(session.id)">
                  <template #reference>
                    <el-icon class="op-icon delete"><Delete /></el-icon>
                  </template>
                </el-popconfirm>
              </div>
            </div>
          </div>
          <div class="status-indicator">
            <span class="dot"></span>
            系统在线
          </div>
        </div>
      </aside>
      
      <!-- 右侧主区域 -->
      <main class="app-main">
        <header class="main-header">
          <div class="header-left">
            <el-icon><Menu /></el-icon>
            <span class="breadcrumb">联想智能助手 / {{ currentSessionTitle }}</span>
          </div>
          <div class="user-profile">
            <el-dropdown v-if="isLoggedIn">
              <el-avatar :size="32" :icon="UserFilled" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="handleLogout">退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button v-else type="primary" size="small" @click="showLogin = true">登录</el-button>
          </div>
        </header>
        
        <div class="chat-content-container">
          <Chat v-if="isLoggedIn && currentPath === '/chat'" :session-id="currentSessionId" :pending-question="pendingQuestion" @session-updated="fetchSessionList" @clear-pending="pendingQuestion = ''" />
          <div v-else-if="isLoggedIn && currentPath === '/knowledge'" class="knowledge-placeholder">
            <el-empty description="知识库管理功能正在集成中..." />
          </div>
          <div v-else class="auth-placeholder">
            <el-empty description="请先登录以体验智能服务">
              <el-button type="primary" @click="showLogin = true">立即登录</el-button>
            </el-empty>
          </div>
        </div>
      </main>

      <!-- 登录/注册 弹窗 -->
      <el-dialog
        v-model="showLogin"
        :title="isRegister ? '新用户注册' : '欢迎回来'"
        width="360px"
        center
        append-to-body
      >
        <el-form :model="authForm" label-position="top">
          <el-form-item label="用户名">
            <el-input v-model="authForm.username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="authForm.password" type="password" placeholder="请输入密码" show-password />
          </el-form-item>
          <div class="auth-actions">
            <el-button type="primary" class="auth-btn" :loading="authLoading" @click="handleAuth">
              {{ isRegister ? '注册' : '登录' }}
            </el-button>
            <div class="auth-switch" @click="isRegister = !isRegister">
              {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
            </div>
          </div>
        </el-form>
      </el-dialog>
    </div>
  </el-config-provider>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import Chat from './views/Chat.vue'
import { Plus, ChatDotRound, Management, Location, Connection, Menu, ChatLineRound, TopRight, Edit, Delete, UserFilled } from '@element-plus/icons-vue'
import { login, register, getSessions, deleteSession, updateSessionTitle } from '@/api/app'
import { ElMessage } from 'element-plus'

const isLoggedIn = ref(!!localStorage.getItem('token'))
const showLogin = ref(false)
const isRegister = ref(false)
const authLoading = ref(false)
const authForm = ref({
  username: '',
  password: ''
})

const currentPath = ref('/chat')
const currentSessionId = ref(Math.random().toString(36).substring(7))
const sessionList = ref([])
const pendingQuestion = ref('')

const goSmartConsult = () => {
  pendingQuestion.value = ''
  currentPath.value = '/chat'
}

const goServiceStation = () => {
  pendingQuestion.value = '我在附近，请帮我找联想授权维修点'
  currentPath.value = '/chat'
}

const goWebSearch = () => {
  pendingQuestion.value = '今天有什么科技新闻？'
  currentPath.value = '/chat'
}

// 编辑标题相关
const editingId = ref(null)
const editingTitle = ref('')
const editInput = ref(null)

const startEdit = (session) => {
  editingId.value = session.id
  editingTitle.value = session.title
  nextTick(() => {
    editInput.value?.focus()
  })
}

const submitEdit = async () => {
  if (!editingId.value) return
  if (!editingTitle.value.trim()) {
    cancelEdit()
    return
  }
  
  try {
    await updateSessionTitle(editingId.value, editingTitle.value.trim())
    const session = sessionList.value.find(s => s.id === editingId.value)
    if (session) session.title = editingTitle.value.trim()
    ElMessage.success('标题已更新')
  } catch (err) {
    ElMessage.error('更新标题失败')
  } finally {
    editingId.value = null
  }
}

const cancelEdit = () => {
  editingId.value = null
  editingTitle.value = ''
}

const handleDelete = async (sid) => {
  try {
    await deleteSession(sid)
    sessionList.value = sessionList.value.filter(s => s.id !== sid)
    if (currentSessionId.value === sid) {
      handleNewChat()
    }
    ElMessage.success('会话已删除')
  } catch (err) {
    ElMessage.error('删除会话失败')
  }
}

const currentSessionTitle = computed(() => {
  const session = sessionList.value.find(s => s.id === currentSessionId.value)
  return session ? session.title : '新会话'
})

const fetchSessionList = async () => {
  if (!isLoggedIn.value) return
  try {
    const data = await getSessions()
    sessionList.value = data
  } catch (err) {
    console.error('Fetch session list error:', err)
  }
}

const handleNewChat = () => {
  currentSessionId.value = Math.random().toString(36).substring(7)
  currentPath.value = '/chat'
}

const handleSessionClick = (sid) => {
  currentSessionId.value = sid
  currentPath.value = '/chat'
}

const handleGoToKnowledge = () => {
  const { protocol, hostname } = window.location
  window.open(`${protocol}//${hostname}:81`, '_blank')
}

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
    }
    const res = await login(authForm.value.username, authForm.value.password)
    localStorage.setItem('token', res.access_token)
    isLoggedIn.value = true
    showLogin.value = false
    ElMessage.success('登录成功')
    await fetchSessionList()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  } finally {
    authLoading.value = false
  }
}

const handleLogout = () => {
  localStorage.removeItem('token')
  isLoggedIn.value = false
  window.location.reload()
}

onMounted(() => {
  if (!isLoggedIn.value) {
    showLogin.value = true
  } else {
    fetchSessionList()
  }
})
</script>

<style>
/* ... (keep existing styles) */
.auth-placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.auth-actions {
  display: flex;
  flex-direction: column;
  gap: 15px;
  margin-top: 20px;
}

.auth-btn {
  width: 100%;
  height: 40px;
  border-radius: 8px;
}

.auth-switch {
  text-align: center;
  font-size: 13px;
  color: var(--primary-blue);
  cursor: pointer;
}

.auth-switch:hover {
  text-decoration: underline;
}
:root {
  /* 明亮科技风配色 */
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
}

body {
  margin: 0;
  padding: 0;
  font-family: 'Inter', 'SF Pro Display', 'PingFang SC', 'Noto Sans SC', sans-serif;
  background-color: var(--main-bg);
  color: var(--text-main);
  -webkit-font-smoothing: antialiased;
}

.app-wrapper {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
}

/* 侧边栏样式 */
.app-sidebar {
  width: 260px;
  background-color: var(--sidebar-bg);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  padding: 20px;
  flex-shrink: 0;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 30px;
}

.logo-info {
  display: flex;
  flex-direction: column;
}

.logo-box {
  width: 36px;
  height: 44px;
  background-color: var(--primary-blue);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 800;
  font-size: 12px;
  letter-spacing: 1px;
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-main);
  line-height: 1.2;
}

.logo-desc {
  font-size: 11px;
  color: var(--text-sub);
  margin-top: 2px;
}

.new-chat-btn {
  width: 100%;
  background-color: #FFFFFF !important;
  border: 1px solid var(--border-color) !important;
  color: var(--text-main) !important;
  height: 44px !important;
  border-radius: 10px !important;
  display: flex !important;
  align-items: center !important;
  justify-content: flex-start !important;
  gap: 10px !important;
  margin-bottom: 25px !important;
  padding: 0 15px !important;
  box-shadow: var(--shadow-sm);
}

.new-chat-btn:hover {
  background-color: #F1F5F9 !important;
  border-color: var(--text-sub) !important;
}

.shortcut {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-sub);
  background: var(--divider-color);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  font-family: 'Inter', sans-serif;
  font-weight: 600;
}

.sidebar-menu {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 15px;
  border-radius: 8px;
  color: var(--text-sub);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  font-weight: 500;
  border: none;
  background: transparent;
  width: 100%;
  text-align: left;
  font-family: inherit;
}

.menu-item:hover {
  background-color: #F1F5F9;
  color: var(--text-main);
}

.menu-item.active {
  background-color: #FFFFFF;
  color: var(--primary-blue);
  box-shadow: var(--shadow-sm);
  position: relative;
}

.menu-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 20%;
  height: 60%;
  width: 3px;
  background-color: var(--primary-blue);
  border-radius: 0 4px 4px 0;
}

.external-icon {
  margin-left: auto;
  font-size: 12px;
  opacity: 0.5;
}

.menu-item:hover .external-icon {
  opacity: 1;
}

.sidebar-footer {
  margin-top: auto;
  padding-top: 20px;
  border-top: 1px solid var(--divider-color);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 50%;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  margin: 10px 0;
  padding-right: 5px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: all 0.2s;
  color: var(--text-sub);
}

.session-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  overflow: hidden;
}

.session-item:hover {
  background-color: #F1F5F9;
  color: var(--text-main);
}

.session-item:hover .session-ops {
  display: flex;
}

.session-ops {
  display: none;
  gap: 5px;
  margin-left: 5px;
  flex-shrink: 0;
}

.op-icon {
  font-size: 14px;
  color: var(--text-sub);
  padding: 4px;
  border-radius: 4px;
  transition: all 0.2s;
}

.op-icon:hover {
  background-color: var(--divider-color);
  color: var(--primary-blue);
}

.op-icon.delete:hover {
  color: #F56C6C;
}

.session-edit-box {
  flex: 1;
  margin-right: 5px;
}

.session-item.active {
  background-color: #FFFFFF;
  color: var(--primary-blue);
  box-shadow: var(--shadow-sm);
}

.session-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.session-title {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-sub);
  text-transform: uppercase;
  margin-bottom: 8px;
}

.history-empty {
  font-size: 12px;
  color: var(--text-sub);
  font-style: italic;
  padding: 10px;
  text-align: center;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-sub);
  padding-top: 10px;
  border-top: 1px solid var(--divider-color);
}

.chat-content-container {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.knowledge-placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dot {
  width: 8px;
  height: 8px;
  background-color: var(--primary-green);
  border-radius: 50%;
  box-shadow: 0 0 4px var(--primary-green);
}

/* 主内容区域样式 */
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: var(--main-bg);
  position: relative;
}

.main-header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 15px;
  color: var(--text-sub);
}

.breadcrumb {
  font-size: 14px;
  font-weight: 500;
}

.chat-container {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0 30px;
}

/* Scrollbar styling */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--text-sub);
}
</style>
