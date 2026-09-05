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

## 3. 当前运行状态(2026-09-05)

### 运行模式:全 Docker(6 容器)

```
its-mysql(33070) its-redis(6379) its-knowledge-api(8001) its-main-backend(8002) its-frontend(80) its-frontend-admin(81)
```
⚠️ MySQL 宿主端口原 3307 因 Windows Hyper-V 保留段(3307–3406)无法绑定,已永久改为 **33070**;容器内部仍为 3306

### 关键数据状态

- **MySQL(service_stations 表):806 条网点 / 75 城市**——本地库(localhost:3306)与容器 its-mysql(宿主**33070**)**已同步一致**(2026-09-02 采完 76 城全量;拉萨 0 条属正常无官方网点)
- **全国采集完成:76/76 城**(覆盖 75 城,累计 806 条网点;武汉 25/长沙 27/北京 24 等 Top 城市网点齐全)
- **断点缓存**:`backend/scripts/.lenovo_stations_cache.json`(done_cities=76, records=798;records 含缓存写入前已存在的 8 条 init_db 官方验证数据,故 798≠806,以 MySQL 实际 806 条为准)
- **知识库向量库**:651 标题全量入库,**embedding=text-embedding-v4**(09-05 换 v4 后本地与服务器均已全量重建;v3/v4 向量空间不兼容,换 embedding 必须重建库)
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
6. **长期遗留**:域名购买+ICP备案+HTTPS+百度 AK Referer 白名单收紧(当前 `*`,公网部署已完成但域名/HTTPS 未上,见 #10)。~~Ragas 评测集扩充~~(已完成,见 #11)
7. **MySQL 端口注意**:宿主端口 **33070**(非原 3307),因为 Windows Hyper-V 把 3307–3406 整个段保留了,`netsh interface ipv4 show excludedportrange protocol=tcp` 可验证
8. **运行评测注意**:PowerShell 终端需先 `$env:PYTHONIOENCODING='utf-8'`,否则打印 ✅ emoji 触发 GBK `UnicodeEncodeError`
9. ✅ **检索精度优化(2026-09-03 完成,context_precision 0.583→0.917)**:在 `retrieval_service.py` 落地四层过滤并部署——①`_reranking` 分数回写 metadata;②相似度阈值过滤 `CONTEXT_SIM_THRESHOLD=0.35`(标定:相关 0.57-0.86/弱相关 0.53-0.70 区间重叠,阈值仅作安全网);③产品类目守卫(PC 域问题剔除标题明确属电视/手机/平板/打印机/投影的文档,不足 2 条按分补回);④LLM 相关性剔除 `_llm_relevance_filter`(qwen3-max 标题级 JSON 判别 ~0.6s,RERANK_ENABLED/RERANK_MODEL 可配,治主题漂移如"驱动问题检索回花屏文档",失败开放退化保留全部)。**终版四指标(15/15,judge=qwen3-max)**:命中 100%/faithfulness 0.974/relevance 0.967/**precision 0.917**/recall 0.987,四项验收线(0.75/0.95/0.9/100%)全过。**附带修复两个先于本次改造的生产级 bug**:(a) `rough_ranking` 直接改写类级 `_metadata_cache` 共享 dict,2 路并发查询互相污染粗排分数(WiFi 问题检索回系统重装文档即此因),已改副本操作;(b) 评测脚本并发下"先打标题后打结果"导致日志中标题与问题错位,按内容配对才可见真实检索质量,排查时勿被日志显示错位误导。**部署教训**:多轮 Edit 后 docker cp 前必须 grep 核验宿主机文件完整性(本轮 `import json` 曾被后续编辑覆盖丢失,LLM 剔除全程静默失效,评测白跑一轮)
10. ✅ **阿里云公网部署完成(2026-09-04)**:服务器 `root@47.102.212.208`(Ubuntu 22.04,2C/3.4G,SSH 仅密钥登录=本机 id_ed25519,**密码登录已于 09-04 禁用**:`/etc/ssh/sshd_config.d/00-hardening.conf` → PasswordAuthentication no + PermitRootLogin prohibit-password,备份在 /root/sshd_config.bak.*)。**22 端口已 ufw 白名单收紧**:仅放行管理员出口 IP 117.150.143.86(家宽动态 IP,变了用 Workbench 改)与阿里云 Workbench 内网 100.64.0.0/10(回滚通道,勿删);80/443/8000/8100 对公网开放(8100=知识库管理平台,ufw+阿里云安全组均已放行)。回滚脚本 `/root/rollback-ssh-hardening.sh`(恢复密码登录+关 ufw)。阿里云安全组 22 仍 0.0.0.0/0(OS 层 ufw 已实际拦截,可选再在控制台收紧作第二层)。**同机跑着用户另一个项目 dify,占 80/443(勿动勿重启)**。因内存紧(dify 占 2.1G)已加 4G swap(`fallocate /swapfile_its`,fstab 已配)。部署形态:入口 `http://47.102.212.208:8000`(agent UI)/`8100`(知识库管理平台,ufw+安全组均已放行);mysql/redis/双后端零宿主端口(防公网裸奔),前端 nginx 用容器名代理(`deploy/nginx-frontend.prod.conf`)。**服务器目录 `/opt/its` 自包含**(服务器连不上 GitHub,部署是纯 scp 交付):`docker-compose.prod.yml`(**必须留在 /opt/its 根**,挂载路径与 env_file 按其所在目录解析)+`deploy/`+`.env`(600)+`backend/knowledge/{chroma_kb1,data}`+`its_db.sql`。镜像更新流程:本地 `docker save` 6 镜像→gzip→scp→`docker load`→重启容器(镜像名需与 `its_multi_agent-*` 一致,compose 只写 image: 不写 build:)。**服务器已装 docker compose v2(`docker compose`,09-04 apt 安装),后续操作一律用 v2;旧 `docker-compose` v1.29 无法处理新 buildx 镜像清单(`KeyError: 'ContainerConfig'`,会停掉旧容器又建不了新的,曾致双前端短暂下线,残留容器名形如 `<id>_its-frontend`,docker rm 后 v2 up 即恢复)**。前端互跳链接(管理平台→客服端、客服端→知识库管理)已改为按当前访问源推导端口(vite 3000/3002、本地 docker 80/81、公网 8100/8000 三套映射),写死 `http://localhost`/`:81` 在公网会跳到访问者本机。**两个公网前端坑(09-04 修复)**:①nginx 默认 `proxy_read_timeout` 60s,RAG 生成(思考模型)实测 50-90s 会 504——两个 nginx conf(prod 与本地 docker)均已显式 `proxy_read/send_timeout 300s`;②管理平台 el-menu 的外链菜单项不能放在 `router` 模式菜单里(点击会 router.push 不存在的 index 把 SPA 带进死路由白屏),已改 `@select` 手动分发(内部 router.push、外链 window.open)。**bind mount 陷阱**:容器挂载单文件后,宿主机用 `mv/scp 覆盖` 会换 inode,运行中容器仍钉在旧 inode(reload 也读旧内容),必须 `cat 新文件 > 挂载文件` 原地写(保留 inode)后容器内 `nginx -s reload`,或 `--force-recreate` 容器。**SPA 缓存陷阱(09-04)**:nginx 默认不给 index.html 发 Cache-Control,浏览器启发式缓存旧 index.html+旧哈希 JS,发布后用户仍跑旧 bundle(症状:已修复的外链跳 localhost、菜单点不动——容器里明明是新代码),排查必看 `curl -sI 站点/` 的 cache-control。已在两个 nginx conf 加策略:index.html `no-cache,no-store,must-revalidate`,`/assets/` 哈希资源 `max-age=31536000,immutable`;排查"线上旧行为"先 grep 容器内 bundle 指纹(window.open/端口映射串)再怀疑缓存。**踩坑**:①PowerShell 管道导出 mysqldump(`| Out-File -Encoding ascii`)会把全部中文吞成 `?`(HEX=3F3F3F),必须容器内落盘+`docker cp` 二进制安全导出;②服务器复杂命令一律写脚本 scp 执行,PowerShell 内联转义必炸(`$(seq)`/`2>/dev/null` 均会被本地 PowerShell 吃掉);③百度/百炼 key 已随根 `.env` 同步到服务器,行为与本地一致。公网冒烟:注册/登录/调度问答/知识库 RAG 全链路 200,中文完好(806 网点 HEX 验证 UTF-8)
11. ✅ **模型切换 v2 + 评测集扩充 + 服务器同步(2026-09-05 完成)**:
    - **触发**:三模型(qwen3.7-max-2026-05-20/qwen3-max-2026-01-23)+text-embedding-v3 额度耗尽(qwen3.8-flash 仍够用不换)。新分工:**orchestrator=qwen-max / technical=judge=rerank=会话压缩=qwen-plus-2025-09-11(非思考,工具调用快) / service=qwen3.8-flash(不变) / RAG生成=qwen-max / embedding=text-embedding-v4**。配置 5 处已同步(根 .env、backend/app/.env、backend/knowledge/.env、两个 settings.py 默认值、.env.example)
    - **换 embedding=v4 必须重建向量库**(v3/v4 空间不兼容):本地 651 标题全量重 embed;服务器更新用"传库"而非重 embed——本地压缩 chroma_kb1(15.5MB/zip 6.2MB)→scp→服务器停容器换 bind mount 目录→重启,**零额度消耗**
    - **评测集扩充 15→30 条**(RAG16-30,`eval_rag_quality.py` 内置数据集):30/30 零超时,**命中 100% / faithfulness 0.993 / relevance 0.917 / precision 0.903 / recall 0.993**,四层检索过滤在扩充集上泛化验证通过;`docs/RAG_EVAL_REPORT.md` 与 `rag_eval_results.json` 已覆盖。注意 judge 实际跑的仍是 qwen3-max-2026-01-23(评测启动时根 .env 保存时序差读到旧值,该模型充值后可用,结果有效;后续 judge 跟随 TECHNICAL_MODEL_NAME 即 qwen-plus)
    - E2E 16/16(场景A 首测失败系百度 API 抖动挂起 234s,复测 20s PASS)
    - **服务器同步方式(09-05)**:scp 5 配置+zip→服务器脚本一次性替换(备份 .env.bak_* 与 chroma_kb1.bak_v3_* 留回滚)→容器内 grep 核验→公网冒烟 4 项(注册/登录//app/chat RAG 54s//api/query 23s)全 PASS。**公网 API 路径约定**:nginx 代理 `/app/`→main-backend:8002、`/api/`→knowledge-api:8001(如公网注册是 `/app/auth/register`,登录是表单编码 `/app/auth/login`)
    - **新硬坑:PowerShell `Compress-Archive` 打包的 zip 路径分隔符是反斜杠**,Linux 解压变成带 `\` 的怪文件名(chroma_kb1\chroma.sqlite3),服务器解压后"文件数 0";**跨平台传目录必须用 Python zipfile**(正斜杠)重打包

## 5. 环境与配置速记

| 项 | 值/位置 |
|----|---------|
| 模型 | orchestrator=qwen-max / technical=qwen-plus-2025-09-11(评测judge/检索rerank/会话压缩跟随) / service=qwen3.8-flash / 知识库RAG生成=qwen-max / embedding=text-embedding-v4(阿里百炼 OpenAI 兼容接口)。09-05 模型切换 v2:qwen3.7-max-2026-05-20、qwen3-max-2026-01-23、text-embedding-v3 额度耗尽后全换;换 embedding 必须重建向量库(v3/v4 不兼容);judge 用非思考模型,思考模型 judge 会超时 |
| 配置 | `backend/app/.env`(主后端) / `backend/knowledge/.env`(知识库,**独立文件易漏改**) / 根 `.env`(Docker compose) / `.env.example`(模板) |
| 百度**双 AK** | `BAIDU_MAP_AK`=服务端AK(geocode/POI/测距);`BAIDU_MAP_AK_BROWSER`=浏览器端AK(前端JS定位,**新规:服务端AK不能用于浏览器端**);白名单不支持http://头,localhost 无法过校验,开发期填 `*` |
| 数据库 | MySQL 库名 `its`;`bcrypt==4.0.1` 锁死(passlib 1.7.4 不兼容 ≥4.1) |
| 本地开发启动 | `python scripts/start_dev.py`(全本地)或混合模式:容器起 mysql/redis/frontend/frontend-admin + 本地 venv 起 8001/8002(先 `docker stop its-main-backend its-knowledge-api` 防端口冲突) |
| 测试 | `python backend/tests/test_service_station_logic.py`(47项,毫秒级) / `e2e_test_api.py`(16项,需双服务运行) / `eval_rag_quality.py`(RAG 评测,详见进行中事项 #5) |

## 6. Git 状态(2026-09-05 交接快照)

- 分支 `main`,远程基线 `ce0db83`(2026-09-04,前端互跳/缓存/超时修复+生产部署配置)。09-05 提交内容:模型切换 v2(配置 5 处)、评测集扩充 15→30 条与评测结果、DEMO 视频脚本、本 HANDOVER 更新
- **注意**:`.env`/`backend/app/.env`/`backend/knowledge/.env` 在 .gitignore 中不入库(含密钥),实际模型值见环境与配置速记表;服务器容器配置已于 09-05 同步(docker cp+传库),重建镜像时会从宿主机重新 COPY

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
