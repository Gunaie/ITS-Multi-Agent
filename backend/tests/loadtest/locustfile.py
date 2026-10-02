"""
ITS 多智能体系统 — Locust 压测脚本（HTTP 黑盒）

两类虚拟用户，按权重混合，复现真实流量结构：
  - BrowseUser（权重 5）：高频访问轻量接口（会话列表 / 工单列表 /
    定位配置 / 健康检查），压 FastAPI + MySQL 连接池 + Redis 的并发承载
  - ChatUser（权重 2）：发起对话（简单问候，走编排器→直答链路），
    覆盖 LLM 调用的端到端长尾（该链路瓶颈在上游百炼 API 配额）

认证说明：注册 5/min、登录 10/min（按 IP 限流），大规模用户无法在
启动窗口内逐一登录，故压测前用 seed_users.py 预置 load_shared 账号，
test_start 时登录一次，全部虚拟用户共享该 JWT（压的是基础设施承载，
业务越权语义由功能测试覆盖）。

用法：
  # 0) 预置账号
  python backend/tests/loadtest/seed_users.py
  # 1) Web UI
  locust -f backend/tests/loadtest/locustfile.py
  # 2) 无头短时压测（20 用户 / 每秒启动 5 个 / 持续 1 分钟）
  locust -f backend/tests/loadtest/locustfile.py --headless \\
         -u 20 -r 5 -t 1m --host http://127.0.0.1:8002 \\
         --csv backend/tests/loadtest/result
"""
import uuid

import requests
from locust import HttpUser, task, between, events

SHARED_USERNAME = "load_shared"
SHARED_PASSWORD = "Load1234!"

# 全局共享 JWT（test_start 时填充）
_SHARED_TOKEN = ""


@events.test_start.add_listener
def _on_test_start(environment, **kwargs):
    """压测开始前用共享账号登录一次，获取全用户复用的 JWT。"""
    global _SHARED_TOKEN
    resp = requests.post(
        f"{environment.host}/auth/login",
        data={"username": SHARED_USERNAME, "password": SHARED_PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    _SHARED_TOKEN = resp.json()["access_token"]


class BrowseUser(HttpUser):
    """轻量接口浏览用户：压本地后端与数据库，不调外部 LLM。"""
    weight = 5
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.client.headers.update({"Authorization": f"Bearer {_SHARED_TOKEN}"})

    @task(5)
    def list_sessions(self):
        self.client.get("/sessions", name="/sessions")

    @task(3)
    def list_tickets(self):
        self.client.get("/support/tickets", name="/support/tickets")

    @task(2)
    def location_config(self):
        self.client.get("/location/config", name="/location/config")

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")


class ChatUser(HttpUser):
    """对话用户：端到端覆盖 LLM 链路（问候类问题，编排器直答）。"""
    weight = 2
    wait_time = between(1.0, 3.0)

    def on_start(self):
        self.client.headers.update({"Authorization": f"Bearer {_SHARED_TOKEN}"})
        self.session_id = f"loadchat_{uuid.uuid4().hex[:12]}"

    @task
    def chat_greeting(self):
        self.client.post("/chat",
                         json={"session_id": self.session_id,
                               "question": "你好", "app_type": "agent"},
                         name="/chat [greeting]",
                         timeout=120)
