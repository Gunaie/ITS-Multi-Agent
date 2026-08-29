<template>
  <div class="chat-main-view">
    <div class="message-list" ref="messagesRef">
      <div v-if="messages.length === 0" class="welcome-screen">
        <div class="welcome-icon">🤖</div>
        <h2>您好，有什么我可以帮您的吗？</h2>
        <p>我是您的智能技术支持专家。您可以咨询技术故障排查，或者寻找附近的联想服务站。</p>
        <div class="suggestions">
          <div class="suggestion-card" @click="useSuggestion('电脑开机黑屏没反应怎么办？')">
            <el-icon><Monitor /></el-icon>
            <span>黑屏故障排查</span>
          </div>
          <div class="suggestion-card" @click="useSuggestion('附近有哪些联想官方维修站？')">
            <el-icon><Location /></el-icon>
            <span>寻找服务中心</span>
          </div>
          <div class="suggestion-card" @click="useSuggestion('如何使用 U 盘重装系统？')">
            <el-icon><Download /></el-icon>
            <span>系统安装指南</span>
          </div>
        </div>
      </div>

      <div 
        v-for="(msg, index) in messages" 
        :key="index" 
        class="message-wrapper"
        :class="msg.role"
      >
        <div class="message-bubble">
          <!-- AI 思考过程 / 推理链 -->
          <div v-if="msg.role === 'assistant' && (msg.thinkingSteps && msg.thinkingSteps.length > 0 || msg.loading)" class="reasoning-chain">
            <div class="reasoning-header" @click="msg.showThinking = !msg.showThinking">
              <span class="thinking-label">
                <el-icon class="thinking-icon" :class="{ 'is-loading': msg.loading }"><Loading v-if="msg.loading" /><List v-else /></el-icon>
                思考过程
              </span>
              <el-icon class="arrow-icon" :class="{ 'is-active': msg.showThinking }"><ArrowDown /></el-icon>
            </div>
            
            <el-collapse-transition>
              <div v-show="msg.showThinking" class="reasoning-content">
                <div v-if="msg.loading && (!msg.thinkingSteps || msg.thinkingSteps.length === 0)" class="thinking-step">
                  <div class="step-indicator active"></div>
                  <div class="step-text">正在分析您的问题...</div>
                </div>
                <div v-for="(step, sIdx) in msg.thinkingSteps" :key="sIdx" class="thinking-step">
                  <div class="step-indicator" :class="{ active: sIdx === msg.thinkingSteps.length - 1 && msg.loading }"></div>
                  <div class="step-body">
                    <div class="agent-tag">{{ step.agent }}</div>
                    <div class="step-text">{{ step.content }}</div>
                    <div v-if="step.handoff" class="handoff-tag">
                      交接 ➡ {{ step.handoff }}
                    </div>
                  </div>
                </div>
              </div>
            </el-collapse-transition>
          </div>

          <!-- 消息内容 -->
          <div class="message-content">
            <div v-if="msg.loading && !msg.content" class="loading-dots">
              <span></span><span></span><span></span>
            </div>
            <div v-else class="markdown-body" v-html="formatContent(msg.content)"></div>
            
            <!-- 引用来源展示 -->
            <div v-if="msg.sources && msg.sources.length > 0" class="message-sources">
              <div class="source-title">参考资料：</div>
              <div class="source-tags">
                <el-tag 
                  v-for="(source, sIdx) in msg.sources" 
                  :key="sIdx"
                  size="small"
                  effect="plain"
                  class="source-tag"
                >
                  {{ source }}
                </el-tag>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="input-container">
      <div class="input-box-wrapper">
        <div class="input-box">
          <el-input
            v-model="userInput"
            placeholder="请输入您的问题... (Shift + Enter 换行)"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 8 }"
            resize="none"
            @keydown.enter.exact.prevent="handleSend"
          />
          <div class="input-actions">
            <div 
              class="location-status" 
              :class="{ 'has-location': !!userLocation, 'is-loading': locationLoading, 'location-error': !userLocation && !locationLoading }" 
              @click="getUserLocation"
              title="点击获取或刷新实时位置"
            >
              <el-icon :class="{ 'is-loading': locationLoading }">
                <Loading v-if="locationLoading" />
                <Warning v-else-if="!userLocation" />
                <Location v-else />
              </el-icon>
              <span>{{ locationLoading ? '正在定位...' : (userLocation ? (userLocation.includes(',') ? '已获取实时位置' : `位置: ${userLocation}`) : '未获取位置 (建议手动设置)') }}</span>
            </div>
            <el-button 
              type="primary" 
              class="send-btn" 
              @click="handleSend"
              :disabled="!userInput.trim() || loading"
              :loading="loading"
            >
              <el-icon><Position /></el-icon>
            </el-button>
          </div>
        </div>
        <div class="input-footer">
          ITS 多智能体平台 • 基于阿里云百炼 & ChromaDB
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, watch } from 'vue'
import { chatWithAgent, chatStreamWithAgent, getSessionDetail } from '@/api/app'
import { marked } from 'marked'
import { Monitor, Location, Download, Position, Loading, List, ArrowDown, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

// 配置 marked 渲染器，使链接在新标签页中打开
const renderer = new marked.Renderer()
renderer.link = ({ href, title, text }) => {
  const titleAttr = title ? ` title="${title}"` : ''
  return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`
}
marked.setOptions({ renderer })

const props = defineProps({
  sessionId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['session-updated'])

const userInput = ref('')
const loading = ref(false)
const locationLoading = ref(false)
const messages = ref([])
const messagesRef = ref(null)
const userLocation = ref(null)

const loadSession = async (sid) => {
  if (!sid) return
  loading.value = true
  try {
    const data = await getSessionDetail(sid)
    messages.value = data.history.map(msg => {
      let content = msg.content
      let thinkingSteps = []
      
      // 从历史记录中提取思考过程 (后端嵌入的格式: **[思考过程]**\n...\n\n---\n\n)
      if (msg.role === 'assistant' && content.includes('**[思考过程]**')) {
        const parts = content.split('**[思考过程]**')
        const thoughtPart = parts[1].split('\n\n---\n\n')
        if (thoughtPart.length > 1) {
          thinkingSteps.push({
            agent: '智能调度专家 (历史推理)',
            content: thoughtPart[0].trim(),
            isReasoning: true
          })
          content = thoughtPart[1].trim()
        }
      }
      
      return {
        ...msg,
        content: content,
        loading: false,
        showThinking: false,
        thinkingSteps: thinkingSteps
      }
    })
  } catch (err) {
    console.error('Load session error:', err)
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

watch(() => props.sessionId, (newSid) => {
  loadSession(newSid)
}, { immediate: true })

const getUserLocation = (force = false) => {
  if (locationLoading.value) return
  
  // 检查 sessionStorage 是否已有有效的经纬度 (包含逗号)
  const savedLocation = sessionStorage.getItem('its_user_location')
  if (!force && savedLocation && savedLocation.includes(',')) {
    userLocation.value = savedLocation
    console.log('Using valid saved location from session:', savedLocation)
    return
  }

  if (navigator.geolocation) {
    locationLoading.value = true
    
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coords = `${position.coords.latitude},${position.coords.longitude}`
        userLocation.value = coords
        sessionStorage.setItem('its_user_location', coords)
        ElMessage.success('位置获取成功')
        locationLoading.value = false
      },
      (error) => {
        console.warn('Error getting location:', error.message)
        locationLoading.value = false
        // 定位失败不弹窗干扰，交给后端 IP 定位兜底
        userLocation.value = null
        sessionStorage.removeItem('its_user_location')
      },
      { timeout: 5000, enableHighAccuracy: false }
    )
  }
}

const handleManualLocation = (customMsg) => {
  ElMessageBox.prompt(customMsg || '请输入您所在的城市（如：武汉、上海）以获得附近服务站信息：', '手动设置位置', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    inputPattern: /^[\u4e00-\u9fa5]{2,20}$/,
    inputErrorMessage: '请输入正确的城市名称（2-20位中文）',
  }).then(({ value }) => {
    userLocation.value = value
    sessionStorage.setItem('its_user_location', value)
    ElMessage.success(`位置已手动设为: ${value}`)
  }).catch(() => {
    ElMessage.info('已取消手动设置')
  })
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTo({
        top: messagesRef.value.scrollHeight,
        behavior: 'smooth'
      })
    }
  })
}

const formatContent = (text) => {
  if (!text) return ''
  return marked(text)
}

const useSuggestion = (text) => {
  userInput.value = text
  handleSend()
}

const handleSend = async () => {
  if (!userInput.value.trim() || loading.value) return
  
  const text = userInput.value
  userInput.value = ''
  
  // 强制检测位置需求：包含关键词或查询地图时
  const locationKeywords = ['维修站', '服务站', '售后', '附近', '导航', '去这里', '地点', '哪里有']
  const needsLocation = locationKeywords.some(k => text.includes(k))
  
  // 如果需要位置但还没获取到，尝试获取一次（带超时）
  if (needsLocation && !userLocation.value && navigator.geolocation) {
    console.log('Detected location-related query, requesting permission...')
    await new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          userLocation.value = `${position.coords.latitude},${position.coords.longitude}`
          console.log('User location acquired:', userLocation.value)
          resolve()
        },
        (error) => {
          console.warn('Error getting location:', error.message)
          resolve() // 报错也继续，使用后端兜底
        },
        { timeout: 5000 }
      )
    })
  }

  messages.value.push({
    role: 'user',
    content: text
  })
  scrollToBottom()
  
  loading.value = true
  const botMsg = {
    role: 'assistant',
    content: '',
    loading: true,
    showThinking: false,
    thinkingSteps: []
  }
  messages.value.push(botMsg)
  scrollToBottom()
  
  let currentAgentName = '智能调度专家'
  
   chatStreamWithAgent(
     { 
       question: text,
       session_id: props.sessionId,
       location: userLocation.value,
       app_type: 'agent'
     },
      (event) => {
      if (event.type === 'agent_updated_stream_event') {
        currentAgentName = event.new_agent
        botMsg.thinkingSteps.push({
          agent: `🔄 切换至: ${currentAgentName}`,
          content: '正在处理您的请求...'
        })
      } else if (event.type === 'run_item_stream_event') {
        if (event.item_type === 'message_output_item') {
          // 处理推理内容
          if (event.reasoning_content) {
            let lastStep = botMsg.thinkingSteps[botMsg.thinkingSteps.length - 1]
            if (!lastStep || !lastStep.isReasoning) {
              lastStep = {
                agent: currentAgentName,
                content: '🤔 正在分析策略: ',
                isReasoning: true
              }
              botMsg.thinkingSteps.push(lastStep)
              botMsg.showThinking = true // 自动展开思考过程
            }
            lastStep.content += event.reasoning_content
          }
          
          // 处理普通内容
          if (event.content) {
            botMsg.content += event.content
            
            // 实时解析引用来源 (例如: 【资料1】 或 [文件名.md])
            const sourceRegex = /【资料(\d+)】|\[([\w\-. ]+\.md)\]/g
            const matches = botMsg.content.match(sourceRegex)
            if (matches) {
              const uniqueSources = [...new Set(matches.map(m => m.replace(/[\[\]]/g, '')))]
              botMsg.sources = uniqueSources
            }
          }
        } else if (event.item_type === 'tool_call_item') {
          botMsg.thinkingSteps.push({
            agent: currentAgentName,
            content: `🛠️ 正在调用工具: ${event.tool_name}...`
          })
        } else if (event.item_type === 'tool_call_output_item') {
          const lastStep = botMsg.thinkingSteps[botMsg.thinkingSteps.length - 1]
          if (lastStep) {
            lastStep.content += ' (已完成)'
          }
        }
      }
      scrollToBottom()
    },
    () => {
      botMsg.loading = false
      loading.value = false
      emit('session-updated')
      scrollToBottom()
    },
    (error) => {
      console.error('Streaming error:', error)
      botMsg.loading = false
      loading.value = false
      if (!botMsg.content) {
        botMsg.content = '抱歉，系统执行过程中发生错误。请检查后端服务连接或稍后再试。'
      }
      scrollToBottom()
    }
  )
}

onMounted(() => {
  // 页面加载时主动尝试获取一次位置
  getUserLocation()
})
</script>

<style scoped>
.chat-main-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  position: relative;
  background-color: var(--main-bg);
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px 20px 150px;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

.welcome-screen {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding-bottom: 50px;
}

.welcome-icon {
  font-size: 60px;
  margin-bottom: 20px;
  filter: drop-shadow(0 4px 10px rgba(59, 130, 246, 0.2));
}

.welcome-screen h2 {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 12px;
  color: var(--text-main);
}

.welcome-screen p {
  font-size: 16px;
  color: var(--text-sub);
  max-width: 500px;
  margin-bottom: 40px;
  line-height: 1.6;
}

.suggestions {
  display: flex;
  gap: 15px;
  flex-wrap: wrap;
  justify-content: center;
}

.suggestion-card {
  background-color: var(--card-bg);
  border: 1px solid var(--border-color);
  padding: 16px 20px;
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  color: var(--text-main);
  font-size: 14px;
  box-shadow: var(--shadow-sm);
}

.suggestion-card:hover {
  border-color: var(--primary-blue);
  background-color: #F8FAFC;
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.message-wrapper {
  display: flex;
  margin-bottom: 32px;
  width: 100%;
  animation: slideUp 0.4s ease-out;
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.message-wrapper.user {
  justify-content: flex-end;
}

.message-bubble {
  max-width: 85%;
  display: flex;
  flex-direction: column;
}

.user .message-bubble {
  background-color: #F0F9FF;
  border: 1px solid #BAE6FD;
  padding: 14px 18px;
  border-radius: 16px 16px 2px 16px;
  color: var(--text-main);
  box-shadow: var(--shadow-sm);
}

.assistant .message-bubble {
  width: 100%;
}

/* 思考过程样式 */
.reasoning-chain {
  background-color: #F8FAFC;
  border-radius: 12px;
  margin-bottom: 12px;
  overflow: hidden;
  border: 1px solid var(--border-color);
}

.reasoning-header {
  padding: 10px 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  background-color: #F1F5F9;
}

.thinking-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-sub);
  font-weight: 600;
}

.thinking-icon {
  font-size: 14px;
}

.thinking-icon.is-loading {
  color: var(--primary-blue);
}

.arrow-icon {
  font-size: 12px;
  color: var(--text-sub);
  transition: transform 0.3s;
}

.arrow-icon.is-active {
  transform: rotate(180deg);
}

.reasoning-content {
  padding: 12px 15px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.thinking-step {
  display: flex;
  gap: 12px;
  position: relative;
}

.step-indicator {
  width: 2px;
  background-color: var(--border-color);
  position: relative;
  margin-left: 4px;
}

.step-indicator.active::after {
  content: '';
  position: absolute;
  top: 0;
  left: -3px;
  width: 8px;
  height: 8px;
  background-color: var(--primary-blue);
  border-radius: 50%;
  box-shadow: 0 0 4px var(--primary-blue);
}

.step-body {
  flex: 1;
}

.agent-tag {
  font-size: 12px;
  font-weight: 700;
  color: var(--primary-blue);
  margin-bottom: 4px;
}

.step-text {
  font-size: 13px;
  color: var(--text-sub);
  line-height: 1.5;
}

.handoff-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background-color: #EFF6FF;
  color: var(--primary-blue);
  border-radius: 4px;
  font-size: 11px;
  margin-top: 6px;
  font-weight: 600;
}

/* AI 回复样式 */
.assistant .message-content {
  color: var(--text-main);
  line-height: 1.8;
  font-size: 15px;
}

.message-sources {
  margin-top: 15px;
  padding-top: 12px;
  border-top: 1px dashed var(--border-color);
}

.source-title {
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 8px;
  font-weight: 600;
}

.source-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.source-tag {
  border-radius: 4px;
  background-color: #F8FAFC;
  border-color: #E2E8F0;
  color: #64748B;
}

.markdown-body :deep(h1), .markdown-body :deep(h2) {
  color: var(--text-main);
  margin: 1.5em 0 1em;
  font-weight: 600;
}

.markdown-body :deep(strong) {
  color: var(--primary-blue);
}

.markdown-body :deep(code) {
  background-color: #F1F5F9;
  padding: 2px 4px;
  border-radius: 4px;
  font-family: monospace;
}

/* 输入区域样式 */
.input-container {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 20px 0 30px;
  background: linear-gradient(to top, var(--main-bg) 80%, transparent);
  z-index: 100; /* 确保输入框始终在最上层 */
}

.input-box-wrapper {
  max-width: 900px;
  margin: 0 auto;
}

.input-box {
  background-color: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  transition: all 0.3s;
  box-shadow: var(--shadow-md);
}

.input-box:focus-within {
  border-color: var(--primary-blue);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1), var(--shadow-md);
}

.input-box :deep(.el-textarea__inner) {
  background-color: transparent;
  border: none;
  color: var(--text-main);
  padding: 8px 0;
  box-shadow: none !important;
  font-size: 15px;
  line-height: 1.5;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

.location-status {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-sub);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  transition: all 0.2s;
}

.location-status:hover {
  background-color: #F1F5F9;
}

.location-status.location-error {
  color: #F59E0B;
}

.location-status.has-location {
  color: var(--primary-blue);
}

.location-status.has-location .el-icon {
  animation: pulse 2s infinite;
}

.location-status.is-loading {
  color: var(--primary-blue);
  cursor: wait;
}

.is-loading {
  animation: rotating 2s linear infinite;
}

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  0% { transform: scale(1); }
  50% { transform: scale(1.1); }
  100% { transform: scale(1); }
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background-color: var(--primary-blue) !important;
  border: none !important;
}

.send-btn:disabled {
  background-color: var(--border-color) !important;
  opacity: 0.5;
}

.input-footer {
  text-align: center;
  font-size: 12px;
  color: var(--text-sub);
  margin-top: 12px;
}

.loading-dots {
  display: flex;
  gap: 6px;
  padding: 10px 0;
}

.loading-dots span {
  width: 8px;
  height: 8px;
  background-color: var(--primary-blue);
  border-radius: 50%;
  animation: dotPulse 1.4s infinite ease-in-out both;
}

.loading-dots span:nth-child(1) { animation-delay: -0.32s; }
.loading-dots span:nth-child(2) { animation-delay: -0.16s; }

@keyframes dotPulse {
  0%, 80%, 100% { transform: scale(0); opacity: 0.3; }
  40% { transform: scale(1); opacity: 1; }
}
</style>
