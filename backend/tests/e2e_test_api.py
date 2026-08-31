"""
项目全功能 E2E 测试（针对运行中的后端服务）

前置条件:
1. MySQL / Redis 已启动
2. 后端服务已运行（二选一）:
       .venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --app-dir backend/app
   或  cd backend/app 后运行 python main.py (开发模式, 端口 8002)
3. 本脚本会消耗少量百度配额(约 18 次)用于维修站/回放场景, 其余场景不消耗

覆盖范围:
- GET  /health                  服务健康
- POST /register + /login       注册登录鉴权
- GET  /sessions                会话列表
- POST /chat                    场景A: 维修站检索(文本定位)
                                场景B: 无定位追问 -> 补充地点 -> 出结果(多轮)
                                场景C: 技术支持(知识/LLM 路由)
                                场景D: 联网搜索(MCP/降级)
                                场景M: 真实故障对话回放(复合意图/路由泄漏/幻觉防复发)
- POST /chat_stream             SSE 流式对话
- POST /chat_knowledge          严格 RAG 知识库问答
- DELETE /sessions/{id}         会话清理

用法:
    .venv/Scripts/python.exe backend/tests/e2e_test_api.py
"""
import os
import sys
import json
import random
import string
import httpx

BASE_URL = "http://127.0.0.1:8002"
TEST_USER = "e2e_tester"
TEST_PASSWORD = "e2e_pass_12345"

_results = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" | {detail}" if detail else ""))
    _results.append((name, ok))
    return ok


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def head(text: str, n: int = 160) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + ("..." if len(text) > n else "")


def chat(client: httpx.Client, headers: dict, session_id: str, question: str,
         location: str = None) -> str:
    payload = {"question": question, "session_id": session_id, "app_type": "agent"}
    if location:
        payload["location"] = location
    resp = client.post(f"{BASE_URL}/chat", json=payload, headers=headers, timeout=240.0)
    resp.raise_for_status()
    return resp.json()["answer"]


def main():
    print("=" * 70)
    print("项目全功能 E2E 测试")
    print("=" * 70)

    client = httpx.Client(timeout=240.0)

    # ------------------------------------------------------------------ 1. 健康
    try:
        resp = client.get(f"{BASE_URL}/health", timeout=5.0)
        check("GET /health", resp.status_code == 200 and resp.json().get("status") == "healthy")
    except Exception as e:
        check("GET /health", False, f"后端未启动? ({e})")
        print("\n请先启动后端:")
        print("  .venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8002 --app-dir backend/app")
        return 1

    # ------------------------------------------------------------ 2. 注册+登录
    suffix = "".join(random.choices(string.ascii_lowercase, k=4))
    username = f"{TEST_USER}_{suffix}"
    r = client.post(f"{BASE_URL}/auth/register", json={"username": username, "password": TEST_PASSWORD})
    check("POST /auth/register", r.status_code in (200, 201), f"status={r.status_code}")
    r = client.post(f"{BASE_URL}/auth/login", data={"username": username, "password": TEST_PASSWORD})
    token = r.json().get("access_token") if r.status_code == 200 else None
    if not check("POST /auth/login", token is not None, f"status={r.status_code}"):
        return 1
    headers = auth_headers(token)

    # ----------------------------------------------------------- 3. 会话列表
    r = client.get(f"{BASE_URL}/sessions", headers=headers)
    check("GET /sessions", r.status_code == 200, f"status={r.status_code}")

    # ------------------------------------------- 4. 场景A: 维修站(文本定位)
    sid_a = "e2e_station_a"
    try:
        ans = chat(client, headers, sid_a, "我在武汉光谷附近找联想维修站，帮我推荐", location="武汉光谷")
        ok = ("联想" in ans) and ("官方授权推荐" in ans or "参考网点" in ans)
        check("Chat 场景A: 维修站检索(文本定位)", ok, head(ans))
    except Exception as e:
        check("Chat 场景A: 维修站检索(文本定位)", False, str(e)[:200])

    # ------------------------------------- 5. 场景B: 无定位追问 -> 补地点(多轮)
    sid_b = "e2e_ask_b"
    try:
        ans1 = chat(client, headers, sid_b, "帮我找附近的联想维修站")
        asks = any(k in ans1 for k in ("城市", "哪里", "位置", "哪个"))
        check("Chat 场景B1: 无定位触发追问", asks, head(ans1))

        ans2 = chat(client, headers, sid_b, "我在武汉光谷")
        ok = ("联想" in ans2) and ("官方授权推荐" in ans2 or "参考网点" in ans2)
        check("Chat 场景B2: 补充地点后出结果", ok, head(ans2))
    except Exception as e:
        check("Chat 场景B: 无定位追问->补地点", False, str(e)[:200])

    # ------------------------------------------------- 6. 场景C: 技术支持路由
    try:
        ans = chat(client, headers, "e2e_tech_c", "我的联想笔记本开机蓝屏怎么办")
        check("Chat 场景C: 技术支持问答", len(ans.strip()) > 30, head(ans))
    except Exception as e:
        check("Chat 场景C: 技术支持问答", False, str(e)[:200])

    # ------------------------------------------------- 7. 场景D: 联网搜索
    try:
        ans = chat(client, headers, "e2e_web_d", "帮我联网搜索一下北京今天的天气")
        ok = len(ans.strip()) > 20
        check("Chat 场景D: 联网搜索(MCP/降级)", ok, head(ans))
    except Exception as e:
        check("Chat 场景D: 联网搜索(MCP/降级)", False, str(e)[:200])

    # ------------------------- 7.5 场景M: 真实故障对话回放(逐字复现线上失败多轮)
    # 复现缺陷: 调度者泄漏内部名 / 越权承诺后编造门店(假地址+XXXX 占位电话)
    sid_m = "e2e_replay_m"
    try:
        replies = [
            chat(client, headers, sid_m, "你好，你是谁"),
            chat(client, headers, sid_m,
                 "电脑开机之后没有任何反应怎么解决，如果解决不了，我准备去附近的维修站维修，告诉我附近维修站在哪"),
            chat(client, headers, sid_m, "告诉我附近维修站在哪"),
            chat(client, headers, sid_m, "我在武汉工程大学流芳校区"),
            chat(client, headers, sid_m, "找到了吗"),
        ]
        full = "\n".join(replies)

        # 断言1: 内部架构词汇零泄漏(用户永远不该看到 agent 内部名)
        leak_words = ("业务服务专家", "技术支持专家", "智能调度专家",
                      "comprehensive_service_agent", "technical_agent",
                      "get_nearby_official_repair_stations")
        leaked = [w for w in leak_words if w in full]
        check("场景M1: 内部架构词汇零泄漏", not leaked,
              f"泄漏词={leaked}" if leaked else "")

        # 断言2: 无编造占位(XXXX 电话是幻觉的铁证)
        check("场景M2: 无编造电话/占位符", "XXXX" not in full)

        # 断言3: 服务轮出现真实工具输出特征(✅/官方授权推荐/参考网点)
        service_replies = replies[2] + "\n" + replies[3] + "\n" + replies[4]
        tool_evidence = any(k in service_replies for k in ("官方授权推荐", "✅", "参考网点"))
        check("场景M3: 服务轮走真实工具查询", tool_evidence, head(service_replies, 120))
    except Exception as e:
        check("场景M: 真实故障对话回放", False, str(e)[:200])

    # ------------------------- 7.7 场景N: 会话历史无重复（防用户消息双写回归）
    try:
        resp = client.get(f"{BASE_URL}/sessions/{sid_m}", headers=headers)
        hist = resp.json().get("history", []) if resp.status_code == 200 else []
        user_msgs = [m for m in hist if m.get("role") == "user"]
        check("会话历史无重复(用户消息=5)", len(user_msgs) == 5,
              f"实际 user 消息数={len(user_msgs)}")
    except Exception as e:
        check("会话历史无重复(用户消息=5)", False, str(e)[:200])

    # ------------------------------------------------------ 8. SSE 流式对话
    try:
        with client.stream(
            "POST", f"{BASE_URL}/chat_stream",
            json={"question": "你好，用一句话介绍你自己", "session_id": "e2e_stream_e", "app_type": "agent"},
            headers=headers, timeout=240.0,
        ) as resp:
            body = "".join(chunk for chunk in resp.iter_text())
        check("POST /chat_stream (SSE)", resp.status_code == 200 and "data:" in body,
              f"status={resp.status_code}, 含事件={'data:' in body}")
    except Exception as e:
        check("POST /chat_stream (SSE)", False, str(e)[:200])

    # ------------------------------------------- 9. 严格 RAG 知识库问答
    try:
        payload = {"question": "如何查询商用选件编号", "session_id": "e2e_kb_f", "app_type": "knowledge"}
        r = client.post(f"{BASE_URL}/chat_knowledge", json=payload, headers=headers, timeout=120.0)
        ans = r.json().get("answer", "") if r.status_code == 200 else ""
        errored = any(k in ans for k in ("发生错误", "查询知识库时", "Not Found", "失败"))
        ok = r.status_code == 200 and len(ans.strip()) > 20 and not errored
        check("POST /chat_knowledge (严格RAG)", ok, head(ans) if ans else f"status={r.status_code}")
    except Exception as e:
        check("POST /chat_knowledge (严格RAG)", False, str(e)[:200])

    # --------------------------------------------------------- 10. 会话清理
    all_ok = True
    for sid in [sid_a, sid_b, "e2e_tech_c", "e2e_web_d", sid_m, "e2e_stream_e", "e2e_kb_f"]:
        try:
            r = client.delete(f"{BASE_URL}/sessions/{sid}", headers=headers)
            all_ok = all_ok and r.status_code == 200
        except Exception:
            all_ok = False
    check("DELETE /sessions/{id} (批量清理)", all_ok)

    client.close()

    # ---------------------------------------------------------------- 汇总
    passed = sum(1 for _, ok in _results if ok)
    total = len(_results)
    print("=" * 70)
    print(f"E2E 结果: {passed}/{total} 通过")
    if passed < total:
        for name, ok in _results:
            if not ok:
                print(f"  - 未通过: {name}")
    return 0 if passed == total else 2


if __name__ == "__main__":
    sys.exit(main())
