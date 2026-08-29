# ITS Multi-Agent 项目 Docker 部署指南

本项目已完成容器化配置，支持通过 Docker Compose 一键启动所有服务（前端、后端、知识库、MySQL、Redis）。

## 🚀 快速启动

### 1. 准备环境
确保你的机器上已安装：
- Docker
- Docker Compose

### 2. 配置环境变量
在项目根目录下创建一个 `.env` 文件（可以参考 `.env.example`）：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写你的 LLM API Key：
```env
AL_BAILIAN_API_KEY=你的阿里云百炼API_KEY
AL_BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MAIN_MODEL_NAME=qwen3.8-27b
SUB_MODEL_NAME=qwen3.7-flash-2026-07-15
```

### 3. 一键启动
在项目根目录下运行：

```bash
docker-compose up -d --build
```

### 4. 访问项目
启动成功后，可以通过浏览器访问：
- **前端界面**: [http://localhost](http://localhost)
- **主后端 API**: [http://localhost:8002](http://localhost:8002)
- **知识库 API**: [http://localhost:8001](http://localhost:8001)

## 🏗️ 架构说明

本项目采用微服务架构，通过 `docker-compose.yml` 编排以下容器：

- **its-frontend**: Vue 3 前端，使用 Nginx 反向代理。
- **its-main-backend**: 基于 FastAPI 的主智能体服务，负责 Orchestrator 调度。
- **its-knowledge-api**: 基于 FastAPI 的知识库服务，负责 RAG 检索。
- **its-mysql**: MySQL 8.0 数据库，存储业务数据。
- **its-redis**: Redis 缓存，存储会话状态。
- **ChromaDB**: 嵌入在知识库服务中的向量数据库（数据持久化在 `./backend/knowledge/chroma_kb1`）。

## 🛠️ 常用命令

- **查看日志**: `docker-compose logs -f`
- **停止服务**: `docker-compose down`
- **重启特定服务**: `docker-compose restart main-backend`
- **清理数据卷**: `docker-compose down -v`

---

*注意：首次启动时，MySQL 可能需要一些时间初始化。如果后端连接失败，请尝试重启后端容器。*
