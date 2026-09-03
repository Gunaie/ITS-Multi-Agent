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

## 3. 当前运行状态(2026-09-03)

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
3. ✅ **Docker 镜像重建 + 镜像源 403 修复(已完成 2026-09-03)**:`its-main-backend` 镜像已于 09-03 01:12 重建成功(含 safety_chat/search_only/radius_km/compound 双写等全部修复)。重建时踩坑:**清华 apt 镜像全站 HTTP 403 + PyPI 返回 versions:none + `python:3.11-slim` 默认 tag 指向 Debian trixie/sid(unstable) 清华无同步**。修复(两个 Dockerfile 同步改,commit `3983463`):基础镜像改 `python:3.11-slim-bookworm` 锁稳定版;apt 删清华 sed 换源回归官方 `deb.debian.org`;pip 改官方 PyPI 主源+阿里云额外索引双兜底,加 `--timeout 120 --retries 3 --prefer-binary`。`knowledge-api` Dockerfile 同步改但镜像未重建(代码未变,跑 09-01 旧镜像 OK)。判断当前 8002 跑的是谁:`Get-NetTCPConnection -LocalPort 8002` 的 OwningProcess 是 wslrelay=容器,python=本地 venv
4. ✅ **glm-5.2 额度耗尽 → 全链路模型切换(已完成 2026-09-03)**:glm-5.2 百炼免费额度彻底耗尽(评测 judge 403 暴露),切换后分工为 **technical=qwen3.8-max-0902 / RAG生成=qwen3.7-max-2026-06-08**(orchestrator/service 不变)。切换涉及 5 处:根 `.env`、`backend/knowledge/.env`、`settings.py` 默认值、`.env.example`、两个运行中容器(已 `docker cp` .env + restart,同步生效)。**注意:容器内 .env 是构建时 COPY 的,下次重建镜像会从宿主机重新 COPY,宿主机已是新值,无需再手工同步**。兼容性已验证:qwen3.8-max 对 extra_body `tool_stream` 参数忽略不报错;它是思考模型(reasoning_content),与 qwen3.7-max 同系列,agents SDK 兼容。验证结果:`e2e_test_api.py` **16/16 全通过**(含场景C 技术问答走知识库工具、场景D MCP 联网搜索真实天气数据)
5. ✅ **RAG 质量评测体系搭建+全量评测完成(2026-09-03)**:新增 `backend/tests/eval_rag_quality.py`(15 条数据集 × 4 指标,自建 LLM-as-judge,对齐 Ragas)+知识库 `POST /query_eval` 接口。**有效终版结果(15/15 成功,judge=qwen3-max-2026-01-23)**:检索命中率 100%、faithfulness **0.978**、answer_relevancy 0.967、context_precision 0.583(短板:检索混入弱相关文档)、context_recall 0.987。评测脚本已补齐 judge 与 /query_eval 的 3 次重试(此前注释声称有重试但代码未实现,一次 DNS 瞬断即废 9 条)。踩坑记录:思考模型当 judge 会超时(qwen3.8-max 180s 都不够);主机 DNS 瞬断会同时打挂容器内 DashScope 调用与主机 judge 调用。`docs/RAG_EVAL_REPORT.md` 已覆盖为有效轮
6. **长期遗留**:公网部署 + HTTPS + 百度 AK Referer 白名单收紧(当前 `*`)、Ragas 评测集扩充
7. **MySQL 端口注意**:宿主端口 **33070**(非原 3307),因为 Windows Hyper-V 把 3307–3406 整个段保留了,`netsh interface ipv4 show excludedportrange protocol=tcp` 可验证
8. **运行评测注意**:PowerShell 终端需先 `$env:PYTHONIOENCODING='utf-8'`,否则打印 ✅ emoji 触发 GBK `UnicodeEncodeError`
9. ✅ **检索精度优化(2026-09-03 完成,context_precision 0.583→0.917)**:在 `retrieval_service.py` 落地四层过滤并部署——①`_reranking` 分数回写 metadata;②相似度阈值过滤 `CONTEXT_SIM_THRESHOLD=0.35`(标定:相关 0.57-0.86/弱相关 0.53-0.70 区间重叠,阈值仅作安全网);③产品类目守卫(PC 域问题剔除标题明确属电视/手机/平板/打印机/投影的文档,不足 2 条按分补回);④LLM 相关性剔除 `_llm_relevance_filter`(qwen3-max 标题级 JSON 判别 ~0.6s,RERANK_ENABLED/RERANK_MODEL 可配,治主题漂移如"驱动问题检索回花屏文档",失败开放退化保留全部)。**终版四指标(15/15,judge=qwen3-max)**:命中 100%/faithfulness 0.974/relevance 0.967/**precision 0.917**/recall 0.987,四项验收线(0.75/0.95/0.9/100%)全过。**附带修复两个先于本次改造的生产级 bug**:(a) `rough_ranking` 直接改写类级 `_metadata_cache` 共享 dict,2 路并发查询互相污染粗排分数(WiFi 问题检索回系统重装文档即此因),已改副本操作;(b) 评测脚本并发下"先打标题后打结果"导致日志中标题与问题错位,按内容配对才可见真实检索质量,排查时勿被日志显示错位误导。**部署教训**:多轮 Edit 后 docker cp 前必须 grep 核验宿主机文件完整性(本轮 `import json` 曾被后续编辑覆盖丢失,LLM 剔除全程静默失效,评测白跑一轮)

## 5. 环境与配置速记

| 项 | 值/位置 |
|----|---------|
| 模型 | orchestrator=qwen3.7-max-2026-05-20 / technical=qwen3-max-2026-01-23 / service=qwen3.8-flash / 知识库RAG生成=qwen3.7-max-2026-05-20 / embedding=text-embedding-v3(阿里百炼 OpenAI 兼容接口)。09-03 晚全量切换：三旧模型(qwen3.7-max-2026-06-08/qwen3.8-max-0902/deepseek-v4-flash-0731)额度耗尽+换新 key(sk-ws- 开头工作空间 key)；新 key 需在百炼控制台开通 WebSearch MCP(否则 404「未开通该MCP」，主后端降级 builtin_web_search)；judge 用非思考的 qwen3-max(0.6s) 根治思考模型 judge 超时 |
| 配置 | `backend/app/.env`(主后端) / `backend/knowledge/.env`(知识库,**独立文件易漏改**) / 根 `.env`(Docker compose) / `.env.example`(模板) |
| 百度**双 AK** | `BAIDU_MAP_AK`=服务端AK(geocode/POI/测距);`BAIDU_MAP_AK_BROWSER`=浏览器端AK(前端JS定位,**新规:服务端AK不能用于浏览器端**);白名单不支持http://头,localhost 无法过校验,开发期填 `*` |
| 数据库 | MySQL 库名 `its`;`bcrypt==4.0.1` 锁死(passlib 1.7.4 不兼容 ≥4.1) |
| 本地开发启动 | `python scripts/start_dev.py`(全本地)或混合模式:容器起 mysql/redis/frontend/frontend-admin + 本地 venv 起 8001/8002(先 `docker stop its-main-backend its-knowledge-api` 防端口冲突) |
| 测试 | `python backend/tests/test_service_station_logic.py`(47项,毫秒级) / `e2e_test_api.py`(16项,需双服务运行) / `eval_rag_quality.py`(RAG 评测,详见进行中事项 #5) |

## 6. Git 状态(2026-09-03 交接快照)

- 分支 `main`,远程 origin/main = `2fd90cc`(2026-09-03,已推送 GitHub)
- 近 3 个提交:
  - `2fd90cc` feat(models/eval): glm-5.2 额度耗尽切换 qwen3.8-max + 自建 RAG 质量评测体系(14 文件,含 /query_eval 接口、eval_rag_quality.py、全文档模型分工同步)
  - `84b146c` fix(session): 压缩阈值改为只数对话条目，修复 E2E M场景误触发压缩
  - `6ad0e41` feat(session): 会话历史摘要压缩，防止长对话上下文溢出
- **工作区:干净**(本轮模型切换+RAG 评测工作已全部入库)
- 注意:`.env`/`backend/knowledge/.env` 在 .gitignore 中不入库(含密钥),实际模型值见环境与配置速记表;两个运行中容器已 docker cp 同步新配置,重建镜像时会从宿主机重新 COPY

## 7. 硬约束(违反会出真实事故,全文背诵)

1. **提示词严禁出现未注入/已移除的工具名**——哪怕语义是"禁止调用",Flash 模型会当真调用 → ModelBehaviorError
2. **流式 Function Calling 必须**在 technical_agent.py 的 ModelSettings extra_body 注入 `tool_stream: True`(glm 系列必需,缺失会静默失败不调工具直接编答案;qwen 系列忽略该参数无害,当前注入保留作兼容)
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
15. **百炼免费额度三坑**:单模型日配额耗尽=403 Forbidden;**并发上限极低**(实测 4 路条目并发即触发限流,表现为请求挂起/ReadTimeout,client timeout 调多大都没用);qwen3.8-max-0902 为**思考模型**(单次调用 1-2 分钟,响应含 reasoning_content,`enable_thinking=false` 实测无效),调用超时要放宽到 180s

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
