# 项目交接文档(新 AI 助手 / 新开发者必读)

> 交接时间:2026-09-01。本文件**自包含**,不依赖任何账号 memory。新接手者只需按顺序读完本文件引用的文档,即可无缝接手。

## 1. 项目一句话

联想售后多智能体智能客服系统(个人全栈项目,模拟联想售后场景):三模型三分支 Agent 编排 + RAG 知识库 + 百度地图官方网点核验 + MCP 联网搜索,Vue3 双前端 + FastAPI 双后端 + Docker Compose 6 容器一键部署。

## 2. 快速上手路径(按顺序读)

| 顺序 | 文档 | 用途 |
|------|------|------|
| 1 | [README.md](../README.md) | 项目全景、技术栈、启动方式 |
| 2 | 本文件 | 当前状态、进行中事项、硬约束 |
| 3 | [docs/IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md) | 从零实现手册;**附录A有18条踩坑速查表,遇到诡异问题先查它** |
| 4 | [docs/DEVELOPMENT_LOG.md](./DEVELOPMENT_LOG.md) | 全周期演进记录,理解"为什么这样设计" |
| 5 | [docs/INTERVIEW_QA.md](./INTERVIEW_QA.md) | 40个问答,最深层的实现细节都在里面 |

## 3. 当前运行状态(2026-09-01)

### 运行模式:全 Docker(6 容器)

```
its-mysql(3307) its-redis(6379) its-knowledge-api(8001) its-main-backend(8002) its-frontend(80) its-frontend-admin(81)
```

### 关键数据状态

- **MySQL(service_stations 表):599 条网点 / 49 城市**——本地库(localhost:3306)与容器 its-mysql(3307)**已同步一致**
- **全国采集进行中:49/76 城**。百度免费配额仅 100次/天(3QPS),今日配额已耗尽熔断;断点缓存在 `backend/scripts/.lenovo_stations_cache.json`(done_cities=["武汉",...共49城])
- **知识库向量库**:529 块 / 约 520 标题(含人工编写 15 篇联想售后指南 + 清洗后的官方爬取文档)
- Redis:会话 JSON 序列化存储

## 4. 进行中事项(接手后立即要做的)

1. **提交未提交的改动并推送**(git 状态见第 6 节;GitHub 近期网络波动,推送失败属环境问题,重试即可)
2. **明天(配额重置后)完成全国采集**:
   ```powershell
   python backend/scripts/import_lenovo_stations.py   # 断点续传剩余 27 城(约 50-70 次配额,一天够)
   python backend/scripts/station_stats.py            # 统计报告
   ```
   ⚠️ 导入脚本写的是 `backend/app/.env` 指向的库(当前=本地3306);**采完必须双写同步到容器库 3307**(参考:读本地全表 → REPLACE INTO 容器,name_addr_hash 唯一键幂等)
3. **长期遗留**:公网部署 + HTTPS + 百度 AK Referer 白名单收紧(当前 `*`)、Ragas 评测集扩充、会话历史摘要压缩

## 5. 环境与配置速记

| 项 | 值/位置 |
|----|---------|
| 模型 | orchestrator=qwen3.7-max / technical=glm-5.2 / service=deepseek-v4-flash / RAG生成=glm-5.2 / embedding=text-embedding-v3(阿里百炼 OpenAI 兼容接口) |
| 配置 | `backend/app/.env`(主后端) / `backend/knowledge/.env`(知识库,**独立文件易漏改**) / 根 `.env`(Docker compose) / `.env.example`(模板) |
| 百度**双 AK** | `BAIDU_MAP_AK`=服务端AK(geocode/POI/测距);`BAIDU_MAP_AK_BROWSER`=浏览器端AK(前端JS定位,**新规:服务端AK不能用于浏览器端**);白名单不支持http://头,localhost 无法过校验,开发期填 `*` |
| 数据库 | MySQL 库名 `its`;`bcrypt==4.0.1` 锁死(passlib 1.7.4 不兼容 ≥4.1) |
| 本地开发启动 | `python scripts/start_dev.py`(全本地)或混合模式:容器起 mysql/redis/frontend/frontend-admin + 本地 venv 起 8001/8002(先 `docker stop its-main-backend its-knowledge-api` 防端口冲突) |
| 测试 | `python backend/tests/test_service_station_logic.py`(47项,毫秒级) / `e2e_test_api.py`(16项,需双服务运行) |

## 6. Git 状态(交接时)

- 分支 `main`,远程 origin/main = `abf63d7`(PR #1 已合并,feature 分支已删)
- **本地领先远程 1 个已提交**:`d4e3b1f` 文档与配置对齐(README/.env.example/docs 标题联想化)——推送失败待重试
- **未提交**(工作区):`docs/` 三份文档大幅扩充(IMPLEMENTATION_GUIDE/INTERVIEW_QA/DEVELOPMENT_LOG)+ 本交接文档 + `import_lenovo_stations.py`(新增脏数据过滤:名称含洗车/充电桩/加油站/驿站/超市/酒店的干扰项不入库)

## 7. 硬约束(违反会出真实事故,全文背诵)

1. **提示词严禁出现未注入/已移除的工具名**——哪怕语义是"禁止调用",Flash 模型会当真调用 → ModelBehaviorError
2. **glm-5.2 流式 Function Calling 必须**在 openai_client.py extra_body 注入 `tool_stream: True`,否则静默失败(不调工具直接编答案)
3. **自定义 MCP 类必须带 `use_structured_content=False` 属性**,否则每次调用 AttributeError 被 SDK 吞掉 → 模型重试至 Max turns exceeded;MCP 客户端用自研 `BailianWebSearchMCP`(httpx POST,协议锁 2024-11-05,3次重试分级日志)
4. **Redis 会话必须 JSON 序列化,禁 pickle**
5. **temperature=0 下模型会模仿会话历史**——会话历史必须过滤工具调用条目(仅保留调度者自己的交接记录);测试必须用唯一 session_id,复用会话=假失败
6. **用户文本说的地点 > 浏览器粗定位**(location_hint_pending 机制);定位四级降级失败必须追问,**禁止静默兜底默认城市**
7. **坐标系契约 BD-09**:前端坐标带 `wgs84:/gcj02:/bd09:` 前缀,后端统一 BD-09
8. **禁止 DROP TABLE**;网点表 name_addr_hash 唯一键幂等写入;表结构靠启动自动迁移
9. **PowerShell Invoke-WebRequest 会把中文变 ???**,测 API 用 httpx;**python -c 内联含中文SQL会被 PowerShell 打碎**,写临时脚本文件执行
10. **百度 scope=2 的 distance 在 POI 顶层**不在 detail_info;配额超限=status 302
11. **容器启动必须 uvicorn --host 0.0.0.0 去 reload**;/health 必须真实存在(httpx 对 404 不报错→假healthy)
12. **Docker Desktop 端口转发言代理会绕过端口冲突检测**——本机其他项目容器(如 psycheflow-chroma 占 8001)可静默劫持流量,排查端口问题先 `docker ps` 全量看
13. nginx 前端容器访问本地后端用 `host.docker.internal:8001/8002`
14. /chat 请求体字段是 **question** 不是 message;登录是 OAuth2 表单格式 `data=` 非 json

## 8. 常用命令速查

```powershell
# Docker 全套
docker compose up -d                    # 启动6容器
docker compose logs -f main-backend     # 看日志
docker compose down                     # 停止
docker compose build main-backend knowledge-api; docker compose up -d main-backend knowledge-api  # 改代码后重建(秒级)

# 本地开发(混合模式)
docker compose up -d its-mysql its-redis frontend frontend-admin
docker stop its-main-backend its-knowledge-api
.\backend\app\.venv\Scripts\python.exe -m uvicorn main:app --port 8002 --app-dir backend/app
.\backend\knowledge\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8001 --app-dir backend/knowledge

# 数据采集
python backend/scripts/import_lenovo_stations.py --cities 武汉 --dry-run
python backend/scripts/station_stats.py

# 测试
python backend/tests/test_service_station_logic.py
```

## 9. 工程约定

- 新增功能必须补测试(纯逻辑下沉为可单测函数;badcase 固化成 E2E 回放)
- 提交信息用中文,-F 文件方式传(避免 PowerShell 内联引号问题)
- 大量使用 async 并发(检索/测距)与超时预算制(每环节预算+外层兜底),新增外部调用要遵守
- 所有对外身份统一"**联想智能技术助手**",禁止出现 ITS/多智能体系统 等内部术语(用户可见文案)
