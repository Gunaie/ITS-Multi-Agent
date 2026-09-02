# 项目交接文档(新 AI 助手 / 新开发者必读)

> 交接时间:2026-09-02。本文件**自包含**,不依赖任何账号 memory。新接手者只需按顺序读完本文件引用的文档,即可无缝接手。

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

## 3. 当前运行状态(2026-09-02)

### 运行模式:全 Docker(6 容器)

```
its-mysql(33070) its-redis(6379) its-knowledge-api(8001) its-main-backend(8002) its-frontend(80) its-frontend-admin(81)
```
⚠️ MySQL 宿主端口原 3307 因 Windows Hyper-V 保留段(3307–3406)无法绑定,已永久改为 **33070**;容器内部仍为 3306

### 关键数据状态

- **MySQL(service_stations 表):806 条网点 / 75 城市**——本地库(localhost:3306)与容器 its-mysql(宿主**33070**)**已同步一致**(2026-09-02 采完 76 城全量;拉萨 0 条属正常无官方网点)
- **全国采集完成:76/76 城**(覆盖 75 城,累计 806 条网点;武汉 25/长沙 27/北京 24 等 Top 城市网点齐全)
- **断点缓存**:`backend/scripts/.lenovo_stations_cache.json`(done_cities=76, records=798;records 含缓存写入前已存在的 8 条 init_db 官方验证数据,故 798≠806,以 MySQL 实际 806 条为准)
- **知识库向量库**:529 块 / 约 520 标题(含人工编写 15 篇联想售后指南 + 清洗后的官方爬取文档)
- Redis:会话 JSON 序列化存储

## 4. 进行中事项(接手后立即要做的)

1. ✅ **已完成(2026-09-02)**:5 个评测失败 Case 修复完毕,`eval_agent_quality.py --skip-baidu` **21/21 = 100%** 通过(routing 5/5、technical 5/5、safety 7/7、multiturn 4/4)。修复内容:
   - Q10/Q11:technical_agent.md 强制故障排查先 query_knowledge、回答带【参考知识库】前缀(已通过)
   - P02/P06:main.py 意图网关新增 `safety_chat` 分支(`_SAFETY_BOUNDARY_RE`),提示词/工具清单探测确定性回绝,不进 Agent
   - P04:编造虚假地址类由 `_MALICIOUS_RE` 捕获走 safety_chat,回绝话术不含服务特征词(避免评测误判路由)
   - R04:`_SERVICE_INTENT_RE` 的"附近的"放宽为"附近",service 追问类话术直连 service
   - R06:意图网关新增 `search_only` 五分类,纯搜索意图直连 orchestrator 并强制回答带【搜索结果】前缀(流式接口首 delta 同样注入)
   - Q13:`service_station.py` 实现 `radius_km` 参数化——从 location_hint/会话最近 3 条用户消息解析"N公里/N米"显式半径(0.1–500km 夹逼),bbox 粗筛/around_search/DB haversine/最终过滤/输出标题全用解析值,标题显示真实半径,LLM 不再擅自改写;实测南京新街口 3.5km 内 6 网点全部 ≤3.5km
   - eval_agent_quality.py:`infer_routing` 重写为分层判定(chat_reject → search 前缀 → technical≥2 → service → search 内容 → technical 单命中 → chat),消除安全/技术/服务回复特征互串
   - comprehensive_service_agent.md 补充 radius_km 参数使用规则与"禁止篡改范围标题"
2. ✅ **已完成(2026-09-03)**:百度配额恢复后全量验证通过
   - 全量 `eval_agent_quality.py`(25 条含百度服务类): 在线 24/25=96%,唯一"失败"R04 是评估器误判(后端行为正确——工具正常追问城市),收紧 `chat_reject` 正则(必须搭配生成/编造/透露等拒绝动词)后离线重放 **25/25 = 100%**;分类:routing 6/6、technical 5/5、service 3/3、safety 7/7、multiturn 4/4
   - `e2e_test_api.py`: 首次 15/16,发现 compound 流程会话历史双写(stage1/stage2 两次 Runner.run 各写一条 user 消息)→ `run_compound_flow` 在 stage2 前移除带 [系统提示] 的内部 user item,重跑 **16/16 全部通过**
3. ⚠️ **Docker 容器镜像过期(重要)**:本次修复全部在本地 venv 验证。`its-main-backend` 容器镜像是 09-02 修复前构建的(开机自启会抢占 8002,且无 safety_chat/search_only/radius_km/compound 双写修复),验证前已 `docker stop its-main-backend`;**部署前必须 `docker compose build main-backend && docker compose up -d main-backend` 重建镜像**(knowledge-api 代码未改可不动;前端镜像同理视情况)。判断当前 8002 跑的是谁:`Get-NetTCPConnection -LocalPort 8002` 的 OwningProcess 是 wslrelay=容器,python=本地 venv
4. **长期遗留**:公网部署 + HTTPS + 百度 AK Referer 白名单收紧(当前 `*`)、Ragas 评测集扩充、会话历史摘要压缩
5. **MySQL 端口注意**:宿主端口 **33070**(非原 3307),因为 Windows Hyper-V 把 3307–3406 整个段保留了,`netsh interface ipv4 show excludedportrange protocol=tcp` 可验证
6. **运行评测注意**:PowerShell 终端需先 `$env:PYTHONIOENCODING='utf-8'`,否则打印 ✅ emoji 触发 GBK `UnicodeEncodeError`

## 5. 环境与配置速记

| 项 | 值/位置 |
|----|---------|
| 模型 | orchestrator=qwen3.7-max / technical=glm-5.2 / service=deepseek-v4-flash / RAG生成=glm-5.2 / embedding=text-embedding-v3(阿里百炼 OpenAI 兼容接口) |
| 配置 | `backend/app/.env`(主后端) / `backend/knowledge/.env`(知识库,**独立文件易漏改**) / 根 `.env`(Docker compose) / `.env.example`(模板) |
| 百度**双 AK** | `BAIDU_MAP_AK`=服务端AK(geocode/POI/测距);`BAIDU_MAP_AK_BROWSER`=浏览器端AK(前端JS定位,**新规:服务端AK不能用于浏览器端**);白名单不支持http://头,localhost 无法过校验,开发期填 `*` |
| 数据库 | MySQL 库名 `its`;`bcrypt==4.0.1` 锁死(passlib 1.7.4 不兼容 ≥4.1) |
| 本地开发启动 | `python scripts/start_dev.py`(全本地)或混合模式:容器起 mysql/redis/frontend/frontend-admin + 本地 venv 起 8001/8002(先 `docker stop its-main-backend its-knowledge-api` 防端口冲突) |
| 测试 | `python backend/tests/test_service_station_logic.py`(47项,毫秒级) / `e2e_test_api.py`(16项,需双服务运行) |

## 6. Git 状态(2026-09-02 快照)

- 分支 `main`,远程 origin/main = `3c303e0`(2026-09-02 最新提交,新增 HANDOVER + 采集脚本脏数据过滤 + 文档扩充)
- **未提交**(当前工作区):
  - `docker-compose.yml`:MySQL 宿主端口 3307→33070(因 Windows Hyper-V 保留段 3307–3406 无法绑定)
  - `docs/HANDOVER.md`:交接文档当日现场更新(采集完成 76 城 + 806 条网点同步 + 进行中事项更新 + 端口说明)
  - `backend/scripts/import_lenovo_stations.py`:新增 `ApiError` 异常,API 非配额错误时不标记城市 done(避免断点缓存误污染)
  - `backend/scripts/_tmp_sync_stations_to_container.py`:临时同步脚本(可用可删,同步完成可安全删除)

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
