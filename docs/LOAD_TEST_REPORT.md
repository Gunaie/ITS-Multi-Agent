# 负载测试报告（Locust）

> 生成时间：2026-10-02 ｜ 工具：Locust 2.46.6 ｜ 脚本：[locustfile.py](../backend/tests/loadtest/locustfile.py)

## 1. 测试环境

| 项 | 配置 |
|---|---|
| 后端 | 主后端 uvicorn 单进程（127.0.0.1:8002） |
| 知识库 | uvicorn 单进程（127.0.0.1:8011，ChromaDB 15 篇精选文档） |
| MySQL | 8.0（Docker，端口 33070，默认 max_connections=151） |
| Redis | 7-alpine（Docker，端口 6379） |
| 客户机 | Windows，Locust 独立 Python 3.11 venv |

## 2. 场景与参数

两类虚拟用户按权重混合，复现真实流量结构：

- **BrowseUser（权重 5）**：`GET /sessions`、`GET /support/tickets`、`GET /location/config`、`GET /health`
  —— 不触发外部 LLM，压 FastAPI + MySQL 连接池 + Redis 的并发承载。
- **ChatUser（权重 2）**：`POST /chat`（问候类问题，编排器直答链路）
  —— 端到端覆盖 LLM 调用长尾。

参数：`-u 20 -r 5/s -t 60s`（20 用户、每秒启动 5 个、持续 1 分钟），认证采用
预置共享账号 + 单一 JWT（注册 5/min、登录 10/min 的按 IP 限流使秒级批量
注册不可行，见第 4 节）。

## 3. 测试结果

**692 请求，0 失败，吞吐 12.4 req/s。**

| 接口 | 请求数 | 失败 | 平均(ms) | p50 | p90 | p95 | p99 | 最大(ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| POST /chat（问候） | 104 | 0 | 997 | 840 | 1500 | 1800 | 3400 | 3643 |
| GET /sessions | 262 | 0 | 23 | 10 | 13 | 18 | 310 | 1303 |
| GET /support/tickets | 161 | 0 | 28 | 6 | 13 | 15 | 1500 | 1724 |
| GET /location/config | 110 | 0 | 19 | 5 | 6 | 7 | 300 | 1294 |
| GET /health | 55 | 0 | 38 | 2 | 10 | 320 | 860 | 864 |
| **聚合** | **692** | **0** | **171** | **9** | **720** | **1100** | **1700** | **3643** |

结论：

- 轻量接口 p50 ≤10ms、p95 ≤18ms，FastAPI + 连接池在 20 并发下余量充足。
- 对话接口平均 ~1s、p95 1.8s，耗时主体在上游百炼 LLM；本地无计算瓶颈。
- 轻量接口偶发 1.3~1.7s 的长尾尖刺（p99 与 p95 落差大），多为 Python GC /
  连接池偶发借还 + Locust 同机调度叠加，占比 <1%。

## 4. 压测发现并修复的真实缺陷

### 缺陷 1：启动不建表，新部署工单接口必 500（已修复）

首轮压测中 `GET /support/tickets` 出现 **51 次 500**，根因：

```
pymysql.err.ProgrammingError: (1146, "Table 'its.support_tickets' doesn't exist")
```

`init_db()`（含 service_stations / support_tickets / message_feedback 建表）
此前只能手动执行，FastAPI 启动流程从不调用；`users` 表因有"首次使用惰性
建表"兜底而幸免。全新 MySQL 数据卷上部署即触发该问题。

修复：[main.py](../backend/app/main.py) 增加 `lifespan`，启动时在线程池中
执行 `init_db()`（3 次重试吸收 MySQL 冷启动竞态），DDL 幂等不破坏存量数据。
修复后实跑验证：692 请求 0 失败、工单接口 200。

### 现象 2：批量注册被限流（属设计行为，非缺陷）

注册 5/min、登录 10/min（slowapi，按 IP），20 用户 4 秒内启动时前 5 个之后
的注册全部 429，形成"注册失败→登录 401→业务请求 401"级联。压测改为
[seed_users.py](../backend/tests/loadtest/seed_users.py) 直连 MySQL 预置
`load_shared` 账号 + test_start 登录一次共享 JWT。

## 5. 千级并发瓶颈推演（Q38："千级并发哪里先崩"）

> 说明：以下为基于真实配置与链路结构的推演，本地未做千级实测；
> 各层数字均来自当前代码/默认配置。

请求链路上的资源约束（按先后顺序）：

| 层 | 当前配置 | 上限行为 |
|---|---|---|
| ① 上游百炼 LLM | 免费额度 QPS/并发极低（实测压测期间即出现 429） | **对话流量最先崩**：排队/超时，p99 抬升 |
| ② 单 uvicorn 进程 | 1 个事件循环，单 CPU 核受限 | CPU 饱和后所有请求排队 |
| ③ anyio 线程池 | 默认容量 **40** | 同步 pymysql 调用超过 40 并发即排队 |
| ④ MySQL 连接池（PooledDB） | `MYSQL_MAX_CONNECTIONS=5`，blocking=True | 第 6 个并发 DB 请求阻塞等连接 |
| ⑤ MySQL 服务端 | max_connections=151 | 超出后新连接被拒 |
| ⑥ slowapi 限流 | 单机内存计数 | 多实例部署时计数不一致 |

**分流量结论：**

- **对话类流量**：瓶颈最先出现在**上游 LLM 配额**（本次实测已见 429），
  其次是单次 LLM 1~3s 的高延迟把单进程在制请求数顶满——本质是"慢调用 +
  外部配额"问题，不是本机算力问题。
- **浏览类流量**：顺序为 **连接池(5) → 线程池(40) → 单 worker CPU**。
  20 并发下连接池 5 已可消化（请求毫秒级、借还快）；并发再上一个数量级时，
  池满后的等待延迟会先于 CPU 显现。

## 6. 扩容与加固建议

1. **多 worker 无状态扩展**：gunicorn -k uvicorn.workers.UvicornWorker
   --workers `2*CPU`，会话在 Redis、认证 JWT 无状态，水平扩展无障碍。
2. **连接池分级调优**：`MYSQL_MAX_CONNECTIONS` 提升到 10~20，并保证
   `worker 数 × 单 worker 池大小 ≤ MySQL max_connections`。
3. **LLM 调用治理**（收益最大）：全局限流信号量 + 相似问题答案缓存(Redis) +
   排队/降级（超时回退小模型或知识库直答）+ 多模型供应商兜底，避免上游
   配额成为单点。
4. **数据访问异步化**：pymysql → asyncmy/aiomysql，去掉 40 线程池天花板。
5. **限流多实例化**：slowapi 后端迁 Redis，统一全局限流计数。
6. **容器化弹性**：K8s Deployment + HPA（按 CPU/在制请求数），MySQL 上
   托管数据库或读写分离。
