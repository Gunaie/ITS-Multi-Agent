# ITS Multi-Agent 项目说明文档

## 1. 项目简介
ITS Multi-Agent（Intelligent Technical Support Multi-Agent System）是一个基于大模型的多智能体智能技术支持系统。该系统旨在通过自动化手段解决用户的技术咨询、故障诊断以及售后服务站导航等需求。

项目采用模块化设计，结合了多智能体协作架构（Multi-Agent Architecture）与检索增强生成（RAG）技术，能够精准理解用户意图并提供专业、实时的技术支持。

## 2. 核心架构

项目由三个主要部分组成：
1.  **前端展示层 (Frontend)**：基于 Vue 3 开发的 Web 交互界面。
2.  **多智能体应用层 (App Backend)**：核心业务逻辑，负责意图识别与任务调度。
3.  **知识服务层 (Knowledge Backend)**：基于 RAG 技术的专业知识库服务。

---

### 2.1 多智能体应用层 (`backend/app/`)
该模块是系统的“大脑”，负责协调不同的专业智能体完成任务。

*   **Orchestrator Agent (智能调度专家)**：
    *   **职责**：作为系统入口，识别用户当前请求的意图。
    *   **调度**：根据意图将任务分发给“技术专家”或“全能业务专家”。
    *   **原则**：严格遵循任务完整性，不推测用户需求，确保工具调用顺序正确。
*   **Technical Agent (资讯与技术专家)**：
    *   **职责**：处理技术咨询、故障排查及实时资讯。
    *   **工具**：对接内部知识库检索工具及外部 MCP 搜索服务。
*   **Service Agent (全能业务智能体)**：
    *   **职责**：处理服务站查询、地点导航及路径规划。
    *   **工具**：对接百度地图 MCP 服务及本地位置解析工具。

### 2.2 知识服务层 (`backend/knowledge/`)
该模块提供了基于文档的检索与回答能力，确保技术建议的准确性。

*   **数据管理**：支持 Markdown 格式的技术文档上传与自动分片（Chunking）。
*   **向量存储**：使用 **ChromaDB** 作为向量数据库，存储文档嵌入（Embeddings）。
*   **检索增强 (RAG)**：通过语义搜索检索相关文档片段，并结合 LLM 生成结构化的专业回答。

### 2.3 前端展示层 (`front/`)
提供直观的用户交互界面。

*   **Chat 界面**：支持流式输出的对话窗口，与后端 Agent 进行实时交互。
*   **知识库管理**：可视化管理上传的文档，查看知识库状态。

---

## 3. 技术栈

*   **后端核心**: Python 3.10+, FastAPI, Uvicorn
*   **大模型框架**: `openai-agents` (多智能体协作), LangChain (RAG 流程)
*   **AI 模型**: OpenAI GPT 系列
*   **数据库**:
    *   **向量库**: ChromaDB
    *   **关系型**: MySQL (基础数据存储)
*   **前端**: Vue 3, Vite, Element Plus, Axios
*   **协议/工具**: MCP (Model Context Protocol) 用于工具集成 (百度地图、Google 搜索)

---

## 4. 项目结构说明

```text
its_multi_agent/
├── backend/
│   ├── app/                # 多智能体应用核心
│   │   ├── infrastructure/ # 基础设施（AI客户端、数据库、日志）
│   │   ├── multi_agent/    # 智能体定义与逻辑
│   │   ├── prompts/        # 智能体系统提示词
│   │   └── tests/          # 测试用例
│   └── knowledge/          # 知识库微服务
│       ├── api/            # 接口定义
│       ├── data/           # 原始技术文档 (Markdown)
│       ├── repositories/   # 数据存储层
│       └── services/       # 检索与生成服务
├── front/
│   └── knowlege_platform_ui/# Vue3 前端项目
└── PROJECT_DOCUMENTATION.md # 本文档
```

---

## 5. 快速开始

### 5.1 环境配置
在 `backend/app` 和 `backend/knowledge` 目录下分别创建 `.env` 文件，配置以下关键变量：
*   `OPENAI_API_KEY`: 您的 OpenAI 密钥
*   `OPENAI_BASE_URL`: API 代理地址（如适用）
*   `DATABASE_URL`: MySQL 连接字符串

### 5.2 启动后端
1.  安装依赖：`pip install -r backend/app/requirements.txt`
2.  启动知识服务：在 `backend/knowledge` 下运行 `python api/main.py`
3.  启动应用服务：根据需要运行 `multi_agent` 中的测试脚本或 API 接口。

### 5.3 启动前端
1.  进入目录：`cd front/front/knowlege_platform_ui`
2.  安装依赖：`npm install`
3.  运行项目：`npm run dev`
