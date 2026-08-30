<template>
  <div class="app-wrapper">
    <div class="sidebar">
      <div class="logo">ITS Knowledge</div>
      <el-menu
        :default-active="activeMenu"
        background-color="var(--sidebar-bg)"
        text-color="var(--text-sub)"
        active-text-color="var(--primary-blue)"
        router
        class="el-menu-vertical"
      >
        <el-menu-item index="/knowledge">
          <el-icon><Files /></el-icon>
          <span>知识库管理</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>智能问答</span>
        </el-menu-item>
        <el-menu-item index="external-consult" @click="handleGoToConsult">
          <el-icon><Service /></el-icon>
          <span>前往咨询平台</span>
          <el-icon class="external-icon"><TopRight /></el-icon>
        </el-menu-item>
      </el-menu>

      <!-- 会话列表 -->
      <div v-if="activeMenu === '/chat'" class="session-sidebar">
        <div class="session-header">
          <span>历史会话</span>
          <el-button type="text" @click="handleNewChat">
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
        <div class="session-list">
          <div v-if="sessionList.length === 0" class="session-empty">暂无记录</div>
          <div 
            v-for="session in sessionList" 
            :key="session.id" 
            class="session-item"
            :class="{ active: currentSessionId === session.id }"
          >
            <div class="session-item-main" @click="handleSessionClick(session.id)">
              <el-icon><ChatLineRound /></el-icon>
              
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
      </div>
    </div>
    <div class="main-container">
      <router-view v-slot="{ Component }">
        <transition name="fade-transform" mode="out-in">
          <component 
            :is="Component" 
            :session-id="currentSessionId" 
            @session-updated="fetchSessionList"
          />
        </transition>
      </router-view>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, ChatLineRound, TopRight, Service, Edit, Delete } from '@element-plus/icons-vue'
import { getSessions, deleteSession, updateSessionTitle } from '@/api/app'
import { ElMessage } from 'element-plus'

const route = useRoute()
const activeMenu = computed(() => route.path)

const currentSessionId = ref(Math.random().toString(36).substring(7))
const sessionList = ref([])

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

const handleGoToConsult = () => {
  window.open('http://localhost:3002', '_blank')
}

const fetchSessionList = async () => {
  try {
    const data = await getSessions()
    sessionList.value = data
  } catch (err) {
    console.error('Fetch sessions error:', err)
  }
}

const handleNewChat = () => {
  currentSessionId.value = Math.random().toString(36).substring(7)
}

const handleSessionClick = (sid) => {
  currentSessionId.value = sid
}

onMounted(() => {
  fetchSessionList()
})
</script>

<style lang="scss" scoped>
.app-wrapper {
  display: flex;
  height: 100vh;
  width: 100%;
  background-color: var(--main-bg);
  color: var(--text-main);
}

.sidebar {
  width: 240px;
  background-color: var(--sidebar-bg);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 10px rgba(0,0,0,0.02);
  z-index: 10;

  .logo {
    height: 60px;
    line-height: 60px;
    text-align: center;
    font-size: 20px;
    font-weight: bold;
    color: var(--primary-blue);
    border-bottom: 1px solid var(--divider-color);
    letter-spacing: 1px;
  }
  
  .el-menu-vertical {
    border-right: none;
    background-color: transparent !important;

    :deep(.el-menu-item) {
      background-color: transparent !important;
      
      &:hover {
        background-color: var(--divider-color) !important;
        color: var(--primary-blue) !important;
      }
      
      &.is-active {
        background-color: #FFFFFF !important;
        color: var(--primary-blue) !important;
        box-shadow: var(--shadow-sm);
      }
    }
  }

  .session-sidebar {
    flex: 1;
    display: flex;
    flex-direction: column;
    margin-top: 20px;
    padding: 0 10px;
    border-top: 1px solid var(--divider-color);
    overflow: hidden;

    .session-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 5px;
      font-size: 12px;
      color: var(--text-sub);
      text-transform: uppercase;
      font-weight: 600;
    }

    .session-list {
      flex: 1;
      overflow-y: auto;
      
      .session-empty {
        text-align: center;
        padding: 20px 0;
        font-size: 12px;
        color: var(--text-sub);
        font-style: italic;
      }

      .session-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 12px;
        border-radius: 6px;
        cursor: pointer;
        margin-bottom: 4px;
        color: var(--text-sub);
        font-size: 13px;
        transition: all 0.2s;

        .session-item-main {
          display: flex;
          align-items: center;
          gap: 10px;
          flex: 1;
          overflow: hidden;
        }

        &:hover {
          background-color: var(--divider-color);
          color: var(--text-main);
        }

        &.active {
          background-color: #FFFFFF;
          color: var(--primary-blue);
          box-shadow: var(--shadow-sm);
        }

        .session-title {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .session-ops {
          display: none;
          gap: 5px;
          margin-left: 5px;
          flex-shrink: 0;
        }

        &:hover .session-ops {
          display: flex;
        }

        .op-icon {
          font-size: 14px;
          color: var(--text-sub);
          padding: 2px;
          border-radius: 4px;
          transition: all 0.2s;

          &:hover {
            background-color: var(--divider-color);
            color: var(--primary-blue);
          }

          &.delete:hover {
            color: #F56C6C;
          }
        }

        .session-edit-box {
          flex: 1;
          margin-right: 5px;
        }
      }
    }
  }
}

.external-icon {
  margin-left: auto;
  font-size: 12px;
  opacity: 0.5;
}

.el-menu-item:hover .external-icon {
  opacity: 1;
}

.main-container {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  background-image: radial-gradient(var(--border-color) 1px, transparent 1px);
  background-size: 30px 30px;
  background-color: var(--main-bg);
}

.fade-transform-leave-active,
.fade-transform-enter-active {
  transition: all 0.4s ease;
}

.fade-transform-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}

.fade-transform-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
