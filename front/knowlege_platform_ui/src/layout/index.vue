<template>
  <div class="app-wrapper">
    <div class="sidebar">
      <div class="logo">ITS Knowledge</div>
      <el-menu
        :default-active="activeMenu"
        background-color="#001529"
        text-color="#bfcbd9"
        active-text-color="#409EFF"
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
            @click="handleSessionClick(session.id)"
          >
            <el-icon><ChatLineRound /></el-icon>
            <span class="session-title">{{ session.title }}</span>
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
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Plus, ChatLineRound } from '@element-plus/icons-vue'
import { getSessions } from '@/api/app'

const route = useRoute()
const activeMenu = computed(() => route.path)

const currentSessionId = ref(Math.random().toString(36).substring(7))
const sessionList = ref([])

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
  background-color: #0d1117;
  color: #c9d1d9;
}

.sidebar {
  width: 240px;
  background-color: #001529;
  border-right: 1px solid #30363d;
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 10px rgba(0,0,0,0.5);
  z-index: 10;

  .logo {
    height: 60px;
    line-height: 60px;
    text-align: center;
    font-size: 22px;
    font-weight: bold;
    background: linear-gradient(90deg, #00f260, #0575e6);
    -webkit-background-clip: text;
    color: transparent;
    border-bottom: 1px solid #30363d;
    letter-spacing: 1px;
  }
  
  .el-menu-vertical {
    border-right: none;
  }

  .session-sidebar {
    flex: 1;
    display: flex;
    flex-direction: column;
    margin-top: 20px;
    padding: 0 10px;
    border-top: 1px solid #30363d;
    overflow: hidden;

    .session-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 5px;
      font-size: 12px;
      color: #8b949e;
      text-transform: uppercase;
    }

    .session-list {
      flex: 1;
      overflow-y: auto;
      
      .session-empty {
        text-align: center;
        padding: 20px 0;
        font-size: 12px;
        color: #8b949e;
        font-style: italic;
      }

      .session-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-radius: 6px;
        cursor: pointer;
        margin-bottom: 4px;
        color: #bfcbd9;
        font-size: 13px;
        transition: all 0.2s;

        &:hover {
          background-color: #161b22;
          color: #fff;
        }

        &.active {
          background-color: #161b22;
          color: #409EFF;
        }

        .session-title {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }
    }
  }
}

.main-container {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  background-image: radial-gradient(#2d333b 1px, transparent 1px);
  background-size: 30px 30px;
  background-color: #0d1117;
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
