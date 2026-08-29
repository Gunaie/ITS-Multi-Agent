<template>
  <div class="chat-main-view">
    <div class="messages" ref="messagesRef">
      <div v-if="messages.length === 0" class="empty-state">
        <el-icon :size="60" color="#30363d"><ChatDotRound /></el-icon>
        <p>开始您的提问，我将严格基于知识库为您解答。</p>
      </div>
      
      <div 
        v-for="(msg, index) in messages" 
        :key="index" 
        class="message-item"
        :class="msg.role"
      >
        <div class="avatar">
          <el-avatar :icon="msg.role === 'user' ? 'User' : 'Service'" :style="{ backgroundColor: msg.role === 'user' ? '#409EFF' : '#00f260' }" />
        </div>
        <div class="content">
          <div class="bubble">
            <div v-if="msg.loading && !msg.content" class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
            <div v-else>
              <!-- 最终内容 -->
              <div class="markdown-body" v-html="formatContent(msg.content)"></div>
              
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
    </div>
    
    <div class="input-area">
      <el-input
        v-model="input"
        placeholder="请输入您的问题..."
        :rows="3"
        type="textarea"
        resize="none"
        @keydown.enter.exact.prevent="handleSend"
      />
      <el-button type="primary" class="send-btn" @click="handleSend" :loading="loading" :disabled="!input.trim()">
        <el-icon><Position /></el-icon> 发送
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, watch } from 'vue'
import { getSessionDetail, chatKnowledge } from '@/api/app'
import { User, Service, Position, ChatDotRound } from '@element-plus/icons-vue'
import { marked } from 'marked'

const props = defineProps({
  sessionId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['session-updated'])

const input = ref('')
const loading = ref(false)
const messages = ref([])
const messagesRef = ref(null)

const loadSession = async (sid) => {
  if (!sid) return
  loading.value = true
  try {
    const data = await getSessionDetail(sid)
    messages.value = data.history.map(msg => ({
      ...msg,
      loading: false,
      thinkingSteps: []
    }))
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

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

const formatContent = (text) => {
  if (!text) return ''
  return marked(text)
}

const handleSend = async () => {
  if (!input.value.trim() || loading.value) return
  
  const question = input.value
  input.value = ''
  
  messages.value.push({
    role: 'user',
    content: question
  })
  scrollToBottom()
  
  loading.value = true
  const botMsg = {
    role: 'assistant',
    content: '',
    loading: true,
    sources: []
  }
  messages.value.push(botMsg)
  scrollToBottom()
  
  try {
    const res = await chatKnowledge({ 
      question,
      session_id: props.sessionId,
      app_type: 'knowledge'
    })
    
    botMsg.content = res.answer
    botMsg.loading = false
    
    // 解析引用来源
    const sourceRegex = /【资料(\d+)】|\[([\w\-. ]+\.md)\]/g
    const matches = botMsg.content.match(sourceRegex)
    if (matches) {
      botMsg.sources = [...new Set(matches.map(m => m.replace(/[\[\]]/g, '')))]
    }
    
    emit('session-updated')
  } catch (err) {
    console.error('Query knowledge error:', err)
    botMsg.content = '抱歉，检索知识库时发生错误。'
    botMsg.loading = false
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

onMounted(() => {
})
</script>

<style lang="scss" scoped>
.chat-main-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: #0d1117;
}

.messages {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  
  .empty-state {
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    color: #8b949e;
    
    p {
      margin-top: 20px;
    }
  }
}

.message-item {
  display: flex;
  margin-bottom: 20px;
  
  &.user {
    flex-direction: row-reverse;
    
    .content {
      align-items: flex-end;
      
      .bubble {
        background-color: #409EFF;
        color: #fff;
        border-top-right-radius: 0;
      }
    }
    
    .avatar {
      margin-left: 10px;
      margin-right: 0;
    }
  }
  
  &.assistant {
    .content {
      align-items: flex-start;
      
      .bubble {
        background-color: #1f242d;
        color: #c9d1d9;
        border: 1px solid #30363d;
        border-top-left-radius: 0;
      }
    }
    
    .avatar {
      margin-right: 10px;
    }
  }
}

.content {
  display: flex;
  flex-direction: column;
  max-width: 85%;
  
  .bubble {
    padding: 12px 16px;
    border-radius: 12px;
    line-height: 1.6;
    font-size: 14px;
    word-break: break-word;

    /* Markdown 样式适配 */
    :deep(p) {
      margin: 0 0 10px 0;
      &:last-child {
        margin-bottom: 0;
      }
    }

    :deep(a) {
      color: #58a6ff;
      text-decoration: none;
      &:hover {
        text-decoration: underline;
      }
    }
    
    :deep(ul), :deep(ol) {
      padding-left: 20px;
      margin: 5px 0;
    }
    
    :deep(code) {
      background-color: rgba(110, 118, 129, 0.4);
      padding: 0.2em 0.4em;
      border-radius: 6px;
      font-family: monospace;
    }
    
    :deep(pre) {
      background-color: #161b22;
      padding: 10px;
      border-radius: 6px;
      overflow-x: auto;
      
      code {
        background-color: transparent;
        padding: 0;
      }
    }
    
    :deep(img) {
      max-width: 100%;
      border-radius: 6px;
      margin: 10px 0;
    }
  }
}

.message-sources {
  margin-top: 15px;
  padding-top: 12px;
  border-top: 1px dashed #30363d;
}

.source-title {
  font-size: 12px;
  color: #8b949e;
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
  background-color: #0d1117;
  border-color: #30363d;
  color: #8b949e;
}

.input-area {
  padding: 20px;
  background-color: #0d1117;
  border-top: 1px solid #30363d;
  display: flex;
  gap: 10px;
  align-items: flex-end;
  
  :deep(.el-textarea__inner) {
    background-color: #161b22;
    border-color: #30363d;
    color: #c9d1d9;
    box-shadow: none;
    
    &:focus {
      border-color: #409EFF;
    }
  }
  
  .send-btn {
    height: auto;
    padding: 10px 20px;
  }
}

.typing-indicator {
  span {
    display: inline-block;
    width: 6px;
    height: 6px;
    background-color: #8b949e;
    border-radius: 50%;
    margin: 0 2px;
    animation: bounce 1.4s infinite ease-in-out both;
    
    &:nth-child(1) { animation-delay: -0.32s; }
    &:nth-child(2) { animation-delay: -0.16s; }
  }
}

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}
</style>
