<template>
  <div class="knowledge-container">
    <div class="page-header">
      <h2>知识库管理</h2>
      <p class="subtitle">Upload and manage your knowledge base documents</p>
    </div>

    <el-card class="upload-card">
      <template #header>
        <div class="card-header">
          <span>文件上传</span>
        </div>
      </template>
      <div class="upload-area">
        <el-upload
          class="upload-demo"
          drag
          action=""
          :http-request="handleUpload"
          multiple
          :show-file-list="false"
        >
          <el-icon class="el-icon--upload"><upload-filled /></el-icon>
          <div class="el-upload__text">
            Drop file here or <em>click to upload</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              Supported files: .txt, .md, .pdf (if supported by backend)
            </div>
          </template>
        </el-upload>
      </div>
    </el-card>

    <div v-if="uploadHistory.length > 0" class="history-section">
      <h3>上传记录</h3>
      <el-table :data="uploadHistory" style="width: 100%" :row-class-name="tableRowClassName">
        <el-table-column prop="fileName" label="文件名" width="280" />
        <el-table-column prop="chunks" label="新增切片数" width="150" align="center" />
        <el-table-column prop="status" label="状态" width="120">
          <template #default="scope">
            <el-tag :type="scope.row.status === 'success' ? 'success' : 'danger'">
              {{ scope.row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="信息" />
        <el-table-column prop="time" label="时间" width="180" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { uploadFile } from '@/api/knowledge'
import { ElMessage } from 'element-plus'

const uploadHistory = ref([])

const handleUpload = async (options) => {
  const { file } = options
  const formData = new FormData()
  formData.append('file', file)

  try {
    const res = await uploadFile(formData)
    uploadHistory.value.unshift({
      fileName: res.file_name,
      chunks: res.chunks_added,
      status: res.status,
      message: res.message,
      time: new Date().toLocaleString()
    })
    ElMessage.success(`File ${file.name} uploaded successfully`)
  } catch (error) {
    uploadHistory.value.unshift({
      fileName: file.name,
      chunks: 0,
      status: 'error',
      message: error.message || 'Upload failed',
      time: new Date().toLocaleString()
    })
    ElMessage.error(`Upload failed for ${file.name}`)
  }
}

const tableRowClassName = ({ rowIndex }) => {
  if (rowIndex === 0) {
    return 'success-row'
  }
  return ''
}
</script>

<style lang="scss" scoped>
.knowledge-container {
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 30px;
  h2 {
    color: var(--text-main);
    margin-bottom: 10px;
  }
  .subtitle {
    color: var(--text-sub);
    font-size: 14px;
  }
}

.upload-card {
  background-color: var(--card-bg);
  border: 1px solid var(--border-color);
  color: var(--text-main);
  margin-bottom: 30px;
  box-shadow: var(--shadow-sm);
  border-radius: 12px;

  :deep(.el-card__header) {
    border-bottom: 1px solid var(--divider-color);
  }
}

.upload-area {
  padding: 20px;
  
  :deep(.el-upload-dragger) {
    background-color: var(--sidebar-bg);
    border-color: var(--border-color);
    
    &:hover {
      border-color: var(--primary-blue);
      background-color: var(--divider-color);
    }
    
    .el-icon--upload {
      color: var(--primary-blue);
    }
    
    .el-upload__text {
      color: var(--text-sub);
      em {
        color: var(--primary-blue);
      }
    }
  }
}

.history-section {
  h3 {
    color: var(--text-main);
    margin-bottom: 20px;
  }
  
  :deep(.el-table) {
    background-color: var(--card-bg);
    color: var(--text-main);
    --el-table-border-color: var(--border-color);
    --el-table-header-bg-color: var(--sidebar-bg);
    --el-table-row-hover-bg-color: var(--divider-color);
    
    th, tr {
      background-color: var(--card-bg);
    }
    
    .success-row {
      background-color: #f0fdf4;
    }
  }
}
</style>
