# 联想售后多智能体智能客服系统 — 从零实现指南

> 本手册面向新人,指导你**从空目录开始一步步复刻**整个系统。每个阶段都包含:目标 → 实现步骤(含关键代码)→ 验收标准 → 踩坑记录。完成全部阶段后,你将得到一个与仓库一致的完整系统。

## 项目最终效果(先看目标)

- 用户在网页上注册登录,询问"笔记本进水了怎么办"(RAG 知识库回答)、"黑屏开不了机"(技术专家)、"附近有哪些维修站"(定位+地图+官方核验)、"北京今天天气"(MCP 联网搜索)
- 系统自动判断意图并路由给不同模型:纯服务诉求秒答、技术问题深度排查、复合问题合并回答
- 全 Docker Compose 一键部署,6 个容器,支持 SSE 流式输出与 7 天会话持久化

技术栈总览:Python 3.11 / FastAPI / agents SDK (OpenAI Agents 风格) / ChromaDB / MySQL / Redis / Vue 3 / Docker Compose / 阿里百炼三模型 + text-embedding-v4 / 百度地图双 AK / LangSmith

---

## 阶段 0:环境准备(半天)

### 0.1 基础软件

| 软件 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 双后端 |
| uv | 最新 | 虚拟环境管理(替代 pip/venv) |
| Node.js | 18+ | 前端构建 |
| MySQL | 8.0 | 用户 + 网点数据(可用 Docker) |
| Redis | 7.x | 会话存储(可用 Docker) |
| Docker Desktop | 最新 | 一键部署(可选,开发期可先不用) |

### 0.2 API 密钥申请

1. **阿里云百炼** `AL_BAILIAN_API_KEY`
   - 开通百炼平台,创建 API Key
   - 需要可用模型:`qwen3.7-max`(调度)、`qwen3.8-max-0902`(技术专家)、`deepseek-v4-flash-0731`(服务专家)、`qwen3.7-max-2026-06-08`(知识库RAG生成)、`text-embedding-v3`(向量化)。原 glm-5.2 因百炼免费额度耗尽已于 2026-09-03 弃用
   - OpenAI 兼容接口地址:`https://dashscope.aliyuncs.com/compatible-mode/v1`

2. **百度地图 AK(注意是两个!)**
   - **服务端 AK**(类型选"服务端"):用于后端地理编码/POI 检索/路网距离,需勾选"地点检索""地理编码""批量算路"服务
   - **浏览器端 AK**(类型选"浏览器端",启用"JavaScript API"服务):用于前端 JS API 浏览器定位
   - ⚠️ 百度新规:**服务端 AK 不支持浏览器端使用**,JS API 必须用浏览器端类型 AK,两者不能混用
   - ⚠️ 白名单格式:不支持 `http://` 协议头;`localhost` 无法通过格式校验,开发期填 `*`,上线收紧为真实域名
   - 免费配额仅约百余次/天,超限返回 `status=302`

3. **LangSmith**(可选):追踪 Agent 全链路,调试 Prompt 神器

### 0.3 配置文件

根目录 `.env.example` 复制为 `.env`,`backend/app/.env` 与 `backend/knowledge/.env` 各自独立(后端 .env 优先级高于根 .env):

```ini
# LLM
AL_BAILIAN_API_KEY=sk-xxx
AL_BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ORCHESTRATOR_MODEL_NAME=qwen3.7-max-2026-06-08
TECHNICAL_MODEL_NAME=qwen3.8-max-0902
SERVICE_MODEL_NAME=deepseek-v4-flash-0731
# 数据库
MYSQL_HOST=localhost / MYSQL_PORT=3306 / MYSQL_USER=root / MYSQL_PASSWORD=xxx / MYSQL_DATABASE=its
REDIS_HOST=localhost / REDIS_PORT=6379
# 知识库
KNOWLEDGE_BASE_URL=http://127.0.0.1:8001
EMBEDDING_MODEL=text-embedding-v4
# 百度双 AK
BAIDU_MAP_AK=服务端AK
BAIDU_MAP_AK_BROWSER=浏览器端AK
# LangSmith
LANGCHAIN_TRACING_V2=true / LANGCHAIN_API_KEY=xxx / LANGCHAIN_PROJECT=xxx
```

**验收**:三个 .env 配齐;`uv` 能创建虚拟环境;密钥全部有效。

---

## 阶段 1:项目骨架与配置中心(半天)

### 1.1 目录结构(先建骨架)

```text
its_multi_agent/
├── backend/
│   ├── app/                    # 主应用后端(Agent 编排)
│   │   ├── main.py             # FastAPI 入口:/auth /chat /chat_stream /sessions /location
│   │   ├── config/settings.py  # pydantic-settings 配置中心(.env 优先级: app/.env > 根 .env)
│   │   ├── multi_agent/        # orchestrator.py / technical_agent.py / service_agent.py
│   │   ├── prompts/            # 三个 agent 的 .md 提示词
│   │   ├── infrastructure/
│   │   │   ├── ai/openai_client.py      # 模型客户端封装(extra_body 注入等)
│   │   │   ├── database/       # init_db.py / session_impl.py / database_pool.py
│   │   │   └── tools/
│   │   │       ├── local/      # baidu_map_tool.py / location_service.py / service_station.py / knowledge_base.py / web_search.py
│   │   │       └── mcp/mcp_servers.py   # 自研 MCP 兼容客户端
│   │   └── Dockerfile
│   ├── knowledge/              # 知识库微服务(独立 .venv!)
│   │   ├── api/main.py / api/routers.py
│   │   ├── services/           # query_service.py(RAG生成) / retrieval_service.py(检索) / ingestion/
│   │   ├── repositories/vector_store_repository.py
│   │   ├── data/crawl/         # 知识库源文档(.md)
│   │   ├── init_kb.py          # 批量入库脚本
│   │   └── Dockerfile
│   ├── tests/                  # 测试金字塔(见阶段 8)
│   └── scripts/                # 网点采集等数据工程脚本
├── front/
│   ├── agent_web_ui/           # 用户咨询平台(Vue 3 + Vite)
│   └── knowlege_platform_ui/   # 知识库管理平台(Vue 3)
├── docker-compose.yml          # 6 容器编排
├── docker/nginx-frontend.conf  # 前端 nginx(反向代理双后端)
├── scripts/start_dev.py        # 本地开发一键启动
└── .env.example
```

**架构原则(为什么这样分):**
- **双后端微服务**:知识库(RAG)与 Agent 编排解耦——知识库可独立重启/扩容/换引擎,主后端只通过 HTTP 调用
- **tools 分 local/ mcp/**:本地工具(地图/知识库/兜底搜索)与远程 MCP 协议工具分开管理
- **prompts 独立 .md 文件**:提示词是 LLM 应用的"源代码",与代码分离便于迭代

**验收**:骨架建好,`python -c "import fastapi"` 在两个 .venv 里都能通过。

---

## 阶段 2:数据层——MySQL + Redis(1 天)

### 2.1 MySQL:用户与网点库

`backend/app/infrastructure/database/init_db.py` 启动时自动建表:

- **users 表**:id / username / `password_hash` / created_at
- **service_stations 表**:id / name / address / province / city / **lat / lng(百度 BD-09)** / phone / source / name_addr_hash 等

两个必踩的坑:

```python
# 坑 1:passlib 1.7.4 与 bcrypt >= 4.1 不兼容
# passlib 内部对 bcrypt 做 72 字节探测,新版 bcrypt 触发长度校验异常 → 注册接口 500
# 解决:requirements.txt 锁死版本
bcrypt==4.0.1  # passlib 1.7.4 不兼容 bcrypt>=4.1, 勿升级

# 坑 2:网点表以 name_addr_hash(MD5(name+address)) 为唯一键实现幂等写入
# 配合启动时的表结构自动迁移(缺列自动 ALTER TABLE ADD),重复导入零副作用
```

### 2.2 Redis:会话存储

`session_impl.py` 自定义 `SimpleSession` 实现 agents SDK 的 Session 协议:

- **必须用 JSON 序列化,禁止 pickle**(反序列化安全风险 + 跨进程兼容性)
- 除当前会话数据外,用 **ZSet** 维护用户 → 会话列表映射(score=最后活跃时间戳),支撑前端"历史会话"侧栏
- **关键设计——历史过滤**:`get_items()` 返回历史时**过滤掉工具调用/工具返回条目**,只保留自然语言消息。原因:temperature=0 下模型会模仿会话历史,若调度者在历史中看到子 Agent 的工具调用记录,会尝试调用**自己并没有的工具**导致 500(详见 Q&A)

**验收**:注册/登录接口通过(hash 校验);会话写入 Redis 后用 `redis-cli` 能看到 JSON 结构。

---

## 阶段 3:知识库 RAG 微服务(2-3 天)

### 3.1 文档准备

`backend/knowledge/data/crawl/` 放 Markdown 文档,命名带序号前缀(如 `004-笔记本进水紧急处理.md`)。文档结构建议:标题 → 适用范围 → 故障现象 → 排查步骤(有序)→ 注意事项。

### 3.2 入库管道 `init_kb.py`

1. 读取全部 .md → 按标题/段落切分 chunk
2. `text-embedding-v3` 向量化(百炼 embedding 接口)
3. 写入 ChromaDB(持久化目录 `chroma_kb1/`),metadata 带 title/source

### 3.3 检索服务(核心调优点)

`retrieval_service.py` 实现混合检索,这是检索质量的胜负手:

```python
# 双路召回
1. 向量检索 top_k=8(语义相关)
2. 标题关键词检索(Jieba 分词,专有名词如 "ThinkPad" 命中率高)

# 三个关键去重/调优点(都是真实踩坑后加的)
- _deduplicate: 标题规范化后比较(去掉 "004-" 序号前缀和 ".md" 后缀)
  → 否则同一文档因向量召回(带前缀)和标题召回(不带前缀)重复出现两次
- 最终返回:同一文档(规范化标题相同)只保留得分最高的 chunk
- 候选池:向量 top_k=8 + 重排候选 20 → 经实测黑屏类查询稳定召回 4 篇不同文档且排名靠前
```

### 3.4 生成与 API

- `query_service.py`:检索片段拼 Prompt → qwen-max 生成回答,**提示词写明身份"联想智能技术助手"**(不要写"多智能体系统"等内部术语,会泄露给用户)
- FastAPI 暴露:`POST /query`(RAG 问答)、`POST /upload`(文档上传,**先查同名文档是否存在**,存在则返回覆盖更新提示)、`GET /health`(供 Docker healthcheck,**必须真实存在**,httpx 对 404 不报错会导致健康检查假绿)
- **平稳退化**:embedding API 异常时自动退化为纯关键词检索,服务不 503

**验收**:重启服务后调用 `/query` 问"笔记本进水了怎么办",回答引用进水文档,`sources` 标注正确;`/health` 返回 200。

---

## 阶段 4:Agent 编排层(3-4 天,项目灵魂)

### 4.1 三个 Agent 定义

`multi_agent/` 下用 agents SDK 定义,每个 Agent 绑定:模型 + 工具集 + 提示词 + handoff 关系。

**三模型分工的理由(面试必考)**:

| Agent | 模型 | 理由 |
|-------|------|------|
| orchestrator(调度) | qwen3.7-max | 意图识别要准,但任务简单;用强模型降低误路由 |
| technical(技术专家) | qwen3.8-max-0902 | Function Calling 稳定(绑知识库+搜索工具);原 glm-5.2 额度耗尽后切换 |
| service(服务专家) | deepseek-v4-flash | 任务是短查询+工具调用,flash 快且便宜 |
| 知识库 RAG 生成 | qwen3.7-max-2026-06-08 | 原 glm-5.2 额度耗尽后切换 |

### 4.2 意图网关三分支(main.py,不走模型的规则路由)

```python
def classify_intent(question: str) -> str:
    # 短句(<=30字) + 服务关键词(维修站/网点/保修/客服电话...) → service_only(直连服务专家,快)
    # 含服务关键词 且 含技术词(黑屏/蓝屏/进水/驱动...) → compound(先技术后服务,合并回答)
    # 其他 → other(走 orchestrator,由模型决定回答或 handoff)
```

**为什么用规则网关而不是让调度模型判断**:纯服务诉求(如"附近维修站")不需要调度模型理解,直连可省一次 LLM 调用(约 1-2 秒);复合意图(如"屏幕坏了帮我找维修站")如果只走单边,会丢掉另一半需求——这是真实用户反馈后修复的。

### 4.3 Handoff(任务交接)

- technical_agent 提供 `handoff` 到 service_agent 的出口(技术问题处理完顺带"找维修站")
- orchestrator 提示词定义**何时交接**(4 类故障关键词清单:硬件15+/软件12+/网络6+/资讯4+;判定原则:口语化描述设备异常一律交接)与**何时不交接**(闲聊、问身份)
- **会话历史需保留调度者自己的交接记录**,只过滤子专家的工具调用——过度过滤会导致调度者多轮后忘记处理逻辑

### 4.4 流式工具调用的 tool_stream 适配(重大坑,glm-5.2 时代发现)

```python
# technical_agent.py
# glm-5.2 走 OpenAI 兼容接口时,流式模式下默认不返回 tool_calls(Function Calling 静默失败!
# 表现:模型不调工具直接编答案)。必须通过 extra_body 注入:
extra_body = {"tool_stream": True}
```

> 现状注(2026-09-03):技术专家已切 qwen3.8-max(忽略该参数,无害),注入保留作 glm 系列兼容;接入任何新模型先跑 Function Calling 兼容性验证(test_model_compat.py)

### 4.5 会话与运行

```python
result = await Runner.run(
    starting_agent,
    input=build_orchestrator_input(session, question),  # 注入定位上下文摘要(见阶段 6)
    session=redis_session,   # 自定义 SimpleSession
    context=session,
)
# chat_stream:Runner.run_streamed + SSE 生成器逐 event 推给前端;外层 120s 超时保护
```

**验收**:
- "黑屏了怎么办" → 技术专家回答(路由正确)
- "附近有哪些维修站" → 服务专家直连(不走调度,日志确认)
- "屏幕坏了帮我找维修站" → 先技术排查再给网点(复合)
- "你好" → 调度者直接寒暄(不误交接)
- 同一会话第二轮带上下文("那呢?"能接住上文)

---

## 阶段 5:工具层——定位与地图(3 天,工程量最大)

### 5.1 多坐标系定位契约

同一地点 WGS-84(浏览器GPS)/GCJ-02(高德)/BD-09(百度)三套坐标系数值差几百米且肉眼无法分辨,程序无法自动判断来源。**契约**:前端传坐标必须带前缀——`wgs84:30.59,114.31` / `gcj02:...` / `bd09:...`(默认 BD-09),后端统一转 BD-09;纯文本地点自动地理编码。

### 5.2 location_service:四级降级链

```python
resolve_user_location(session, location_hint):
    1. location_hint(用户本轮明确说的地点,优先级最高——打字说的地方 > 浏览器猜的)
    2. 会话缓存(GPS 24h / 文本 2h / IP 30min 差异化 TTL)
    3. 文本地理编码(hint 提取城市名传入百度 geocode 的 city 参数限制范围,
       避免"湖北中医药大学黄家湖校区"这类不含城市名的地址被解析到同校另一校区)
       → 进阶:geocode 与 POI 名称检索并行交叉校验,粗精度或漂移>3km 时信任 POI 结果
    4. IP 定位(仅公网客户端 X-Forwarded-For 有效,服务器本机 IP 无意义;WGS-84 需转 BD-09)
    全部失败 → 返回 None → Agent 主动追问用户城市,禁止静默兜底默认城市
```

### 5.3 网点检索与官方核验引擎(service_station.py)

**检索**:三个关键词(客户服务中心/授权服务站/维修)**asyncio.gather 并行**检索,POI 召回从约 10 提升到 26;搜索半径 200km(`SEARCH_RADIUS_KM`);超时预算:定位 4s + 检索 8s + 测距 6s,外层 22s 兜底。

**官方核验加权评分**(地图 POI 鱼龙混杂,纯字符串判断不可靠):

```python
score = 0.6 * phone_match(电话归一化匹配官方库,最强证据:座机区号/400号段/分机/多电话拆分,任一命中即通过)
      + 0.25 * name_ratio(编辑距离 + 品牌词校验)
      + 0.15 * addr_jaccard(地址分词 Jaccard 相似度)
>= 阈值 → 判官方并回填官方库全字段(修正地图侧错误坐标/电话)
去重:电话一致,或名称相似且 haversine 间距 < 150m → 合并
输出分级:✅ 官方授权店 / ❓ 疑似官方 / ⚠️ 第三方参考
```

实测:武汉 26 个 POI 中官方库命中全部自动标 ✅,祛痘店/华为服务店/加油站便利店全部低分排除。

**距离口径**:路网距离优先(百度**批量** Route Matrix,一次请求算完所有点位,性能从 15s 优化到 5s 内),失败兜底 haversine 直线距离,输出时明确标注"路网距离";⚠️ scope=2 时 distance 字段在 POI 顶层而非 detail_info 内(读错位置会得到 0 值污染排序)。

### 5.4 数据采集工程(backend/scripts/import_lenovo_stations.py)

免费配额约百余次/天,全国 76 城怎么采?四个机制:**逐城入库**(中断不丢)、**配额熔断**(一遇 302 立即停)、**断点续传**(已完成城市写缓存,重跑跳过)、**幂等写入**(name_addr_hash 唯一键)。支持 `--cities 武汉` / `--dry-run`。

**验收**:"我在湖北工业大学,附近有哪些维修站" → 定位到武汉洪山区,最近官方店约 4.5km,官方店全在 50km 外时报告头部出现定位提醒。

---

## 阶段 6:MCP 联网搜索(2 天,最深的一次排障)

百炼平台提供 MCP WebSearch 服务,但**标准 SDK 客户端全部连不上**。排障四层递进:

1. `MCPServerSse` 连 `/WebSearch/sse` → 返回空 body(**SSE 端点已废弃**)
2. `MCPServerStreamableHttp` + 最新协议版本 → HTTP 500(**仅支持 2024-11-05 旧协议**)
3. **自研鸭子类型 MCP 客户端**:httpx POST 实现 initialize 握手 → tools/list → tools/call,协议头锁定 `2024-11-05`,3 次重试分级日志(前2次 INFO,第3次 WARNING)
4. 服务连上了但模型还是说"无法联网"→ **agents SDK 会直接访问 `server.use_structured_content` 属性**,自定义类缺该属性 → 每次调用 AttributeError → 被 SDK 的 `failure_error_function` 吞成错误文本回给模型 → 模型以为工具坏了反复重试 → **Max turns (10) exceeded**。补上 `use_structured_content=False` 后真正跑通

配套规则:
- 工具命名:本地兜底工具叫 `builtin_web_search`,MCP 侧工具名是 `bailian_web_search`(**不能重名**)
- **提示词严禁提及未注入/已移除的工具名**——哪怕语义是"禁止调用",Flash 模型会把提示词里的工具名当真
- MCP 就绪时自动从工具列表摘除本地兜底工具(消除同名误选)

**验收**:问"北京今天天气"返回实时结果;断网/Key 失效时优雅降级到知识库。

---

## 阶段 7:前端(2-3 天)

### 7.1 咨询平台 agent_web_ui(Vue 3 + Vite)

- 聊天气泡 + Markdown 渲染 + 思考过程下拉框 + SSE 逐字渲染(fetch ReadableStream 消费 `/chat_stream`)
- 定位状态栏:四级降级链的前半段在浏览器——`navigator.geolocation`(3s 超时,大陆桌面浏览器底层依赖 Google 服务必失败)→ **百度 JS API 浏览器定位**(懒加载 `api.map.baidu.com/api?v=1.0&type=webgl&ak=浏览器端AK`,AK 从后端 `/location/config` 接口下发;onMounted 预热 script;定位首调冷启动 >10s,设 15s 超时 + 失败自动重试一次)→ 后端 IP 定位 → 手动输入城市
- 定位成功写 `sessionStorage.its_user_location`(BD-09 直出,百度 JS API 原生返回 BD-09 零转换)
- ⚠️ CSS 细节:loading 旋转动画选择器写 `.el-icon.is-loading`,写全局 `.is-loading` 会把整个文字一起转
- 欢迎页:图标 + 标题 + 4 张建议卡片(不要再加一层重复的小药丸标签)

### 7.2 管理平台 knowlege_platform_ui

文档上传(.md/.pdf/.docx/.txt 白名单,与后端校验一致)/ 检索调试 / 会话管理;全中文界面。

**验收**:两个平台联通;上传文档后立即能用相关问题检索到;SSE 流式逐字显示。

---

## 阶段 8:测试金字塔与可观测性(2 天)

```text
backend/tests/
├── test_service_station_logic.py   # 47 项纯逻辑断言(电话/名称/地址匹配、坐标转换、
│                                   #   去重合并、追问链路),毫秒级零依赖,自研 check() 计数
├── smoke_test_station_tool.py      # 工具冒烟:真实 geocode → 并行检索 → 核验 → 距离
├── e2e_test_api.py                 # 16 项 API E2E:健康/鉴权/会话/四类对话/流式/RAG/故障回放
├── test_web_search_routing.py      # 路由回归:实时资讯必须走 MCP 主搜索(免地图配额可天天跑)
├── eval_agent_quality.py           # 25 项质量评测:路由/内容/安全/响应时间
└── test_model_compat.py / test_agents_sdk_glm.py  # 模型兼容性
```

LLM 测试的三个特殊设计:
1. **每个 E2E 用唯一 session_id**——temperature=0 下模型会模仿会话历史,复用会话产生假失败
2. **故障对话回放**——把线上 badcase 固化成 E2E,防复发
3. **配额预算管理**——百度配额敏感场景每次运行消耗可预估、可拆分

质量评测结果(25 项):路由正确率 84% / 内容完整率 92% / 安全合规 100% / 平均响应 4.24s。

LangSmith:`LANGCHAIN_TRACING_V2=true` 后全链路可视——哪次路由错了、哪个工具参数传歪了,Trace 里一目了然,**调 Prompt 的第一工具**。

**验收**:`python backend/tests/test_service_station_logic.py` → 47/47 通过。

---

## 阶段 9:Docker 一键部署(1 天)

### 9.1 docker-compose.yml(6 容器)

```yaml
its-mysql(3307:3306, healthy) / its-redis(6379, healthy)
its-knowledge-api(8001) / its-main-backend(8002)   # depends_on 上述两容器 healthy
its-frontend(80) / its-frontend-admin(81)           # nginx,代理指向 host.docker.internal:8001/8002
```

### 9.2 必踩的坑(每一条都真实付出过时间)

1. **容器启动命令必须用生产模式**:`python main.py`(内部 host=127.0.0.1+reload)会导致端口映射失效宿主机连接被断开 → 必须 `uvicorn main:app --host 0.0.0.0`,**且不要 reload**
2. **healthcheck 接口必须真实存在**:用 httpx 检查要区分 404(假绿),知识库补了 `/health` 路由
3. **nginx 代理用 `host.docker.internal:8001/8002`**:混合模式下(容器前端+本地后端)必须走宿主机别名;全容器模式可直连容器名
4. **数据分裂**:本地 venv 和容器若连不同 MySQL 实例,数据不一致且难察觉——统一库实例
5. **构建加速**:Dockerfile 内配置清华 pip 镜像源;依赖层放前、代码层放后,改代码不重装依赖(重建 5-10 秒)
6. **同机其他项目容器端口劫持**:Docker Desktop 的端口转发言代理可绕过端口冲突检测——本机 Chroma 容器占用 8001 后,知识库流量被静默劫持(前端报"查询错误"),`docker ps` 排查 + `docker stop` 释放
7. `.dockerignore` 必配:.venv/data/cache 排除,镜像从 5GB+ 降到 1.3-1.7GB

### 9.3 两种运行模式

```powershell
# 全 Docker(部署/演示)
docker compose up -d
# 混合模式(日常开发:容器 MySQL/Redis/前端 + 本地 venv 后端,改代码秒生效)
docker compose up -d its-mysql its-redis frontend frontend-admin
docker stop its-main-backend its-knowledge-api   # compose 会顺带起后端容器,手动停掉防端口冲突
.\backend\app\.venv\Scripts\python.exe -m uvicorn main:app --port 8002 --app-dir backend/app
.\backend\knowledge\.venv\Scripts\python.exe -m uvicorn api.main:app --port 8001 --app-dir backend/knowledge
```

本地开发一键启动(纯本地,不用 Docker):`python scripts/start_dev.py`(Knowledge UI :3000 / Agent UI :3002 / 双后端)。

**验收**:6 容器全 healthy;E2E 16 项全绿(打容器端口);首次构建 5-8 分钟,后续重建秒级。

---

## 附录 A:踩坑清单速查

| # | 坑 | 一句话解法 |
|---|----|-----------|
| 1 | passlib 1.7.4 + bcrypt≥4.1 → 注册500 | 锁 `bcrypt==4.0.1` |
| 2 | glm 系列流式不返回 tool_calls | extra_body 注入 `tool_stream: True`(现注入在 technical_agent.py ModelSettings;qwen 系列忽略该参数) |
| 3 | 自定义 MCP 类 → Max turns exceeded | 补 `use_structured_content=False` 属性 |
| 4 | 百炼 MCP:SSE 废弃/新协议500 | 自研 httpx POST 客户端,协议锁 `2024-11-05` |
| 5 | 提示词里写"禁止调 X"反而调 X | 提示词不出现未注入工具名 |
| 6 | 多轮后模型模仿历史调用不存在的工具 | 会话历史过滤工具调用条目 |
| 7 | temperature=0 复用会话 → E2E 假失败 | 每用例唯一 session_id |
| 8 | PowerShell Invoke-WebRequest 中文变 ??? | 用 httpx 或浏览器测 |
| 9 | 地理编码跨城错(校区不含城市名) | hint 提取城市传 geocode `city` 参数 + POI 交叉校验 |
| 10 | scope=2 的 distance 读不到 | 在 POI 顶层不在 detail_info |
| 11 | Redis 会话用 pickle | 必须 JSON |
| 12 | 容器 host=127.0.0.1 + reload | uvicorn --host 0.0.0.0 去 reload |
| 13 | 知识库 /health 不存在假健康 | 补真实路由 |
| 14 | 本机 8001 被其他项目容器劫持 | docker ps 排查,Docker Desktop 转发绕过冲突检测 |
| 15 | 服务端 AK 跑 JS API 被禁 | 新规:浏览器端必须用浏览器端类型 AK |
| 16 | 百度白名单填 http://localhost 报格式错 | 不带协议头;localhost 无法过校验,开发期填 * |
| 17 | 百度定位首调 >10s 超时 | onMounted 预热 + 15s 超时 + 失败重试一次 |
| 18 | 同一文档双路召回重复 | 标题规范化(去序号前缀)后再去重 |

## 附录 B:命令速查

```bash
# 单测(47项,毫秒级)            # E2E(需双服务)              # 网点采集
python backend/tests/test_service_station_logic.py
python backend/tests/e2e_test_api.py
python backend/scripts/import_lenovo_stations.py --cities 武汉 --dry-run

# Docker                        # 看日志                      # 停止
docker compose up -d            docker compose logs -f main-backend
docker compose down
```
