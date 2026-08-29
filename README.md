# ITS 多智能体技术支持系统 (ITS Multi-Agent)

基于多智能体协作架构与 RAG（检索增强生成）技术的智能技术支持系统，旨在通过分工明确的 AI 专家团，为用户提供精准的硬件故障诊断、软件操作指导及周边服务查询。

## 🚀 快速启动

在项目根目录下，使用统一的开发模式启动脚本：

```powershell
python start_dev.py
```

该脚本将一键启动以下服务：
- **管理平台 (UI)**: [http://localhost:3000](http://localhost:3000)
- **咨询平台 (UI)**: [http://localhost:3002](http://localhost:3002)
- **知识库后端 (API)**: [http://127.0.0.1:8001](http://127.0.0.1:8001)
- **应用后端 (API)**: [http://127.0.0.1:8002](http://127.0.0.1:8002)

## 🏗️ 项目架构

项目采用微服务解耦设计，分为三个核心部分：

### 1. 应用后端 (`backend/app`)
作为系统的“大脑”与“神经中枢”，负责 Agent 编排与业务逻辑。
- **智能调度专家 (Orchestrator)**: 基于意图识别，将任务分发给技术或服务专家。
- **多智能体协作**: 采用 `tiny-agents` 框架实现 Agent 间的任务交接（Handoff）。
- **外部能力集成**: 通过 **MCP (Model Context Protocol)** 接入联网搜索与高德地图服务。
- **会话持久化**: 基于 Redis + Pickle 实现分布式 Session 管理，支持多平台会话隔离。

### 2. 知识库后端 (`backend/knowledge`)
专为技术文档设计的 RAG 引擎。
- **混合检索**: 结合向量检索 (ChromaDB) 与标题关键词匹配 (Jieba)。
- **平稳退化**: 当嵌入模型 API 异常时，自动退化至关键词检索，确保系统高可用。
- **数据管理**: 支持批量 Markdown 文档解析、切分与入库。

### 3. 前端界面 (`front`)
- **咨询平台 (`agent_web_ui`)**: 面向最终用户，提供流式（SSE）对话体验。
- **管理平台 (`knowlege_platform_ui`)**: 面向管理员，用于知识库维护与检索效果调试。

## 🛠️ 技术栈

- **语言**: Python 3.10+, JavaScript (Vue 3)
- **AI 模型**: 阿里百炼通义千问系列 (Qwen-Max, Qwen-Flash)
- **数据库**: MySQL (用户数据), Redis (会话数据), ChromaDB (向量数据)
- **协议**: MCP (Model Context Protocol), SSE (Server-Sent Events)

## 📂 目录说明

```text
its_multi_agent/
├── backend/
│   ├── app/           # 主应用后端 (Agent 编排与工具集成)
│   └── knowledge/     # 知识库后端 (RAG 检索与文档管理)
├── front/
│   ├── agent_web_ui/  # 咨询平台前端
│   └── knowlege_platform_ui/ # 管理平台前端
├── data/              # 共享数据目录 (MySQL/Chroma 数据持久化)
└── start_dev.py       # 统一开发模式启动脚本
```

## ⚠️ 开发注意事项
- **环境隔离**: `backend/app` 和 `backend/knowledge` 拥有各自的 `.venv` 环境，请确保在对应环境下运行或使用 `start_dev.py`。
- **环境变量**: 请务必在各后端的 `.env` 文件中配置正确的 `API_KEY` 与服务地址。
