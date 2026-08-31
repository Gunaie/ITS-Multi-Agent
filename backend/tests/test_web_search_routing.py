"""
联网搜索路由测试（免百度配额）：验证实时资讯问题走 MCP 主搜索而非本地兜底。

前置: 后端 8002 已启动。
判定: 回答中不应出现本地兜底工具的降级占位文案
     （"无法实时获取" / "暂时无法获取" / "建议您查看手机自带天气应用"）。

用法:
    .venv/Scripts/python.exe backend/tests/test_web_search_routing.py
"""
import random
import string
import sys
import httpx

BASE_URL = "http://127.0.0.1:8002"
FALLBACK_MARKS = ("无法实时获取", "暂时无法获取", "建议您查看手机自带天气应用", "实时资讯服务目前忙")


def main() -> int:
    client = httpx.Client(timeout=180.0)
    username = "wsroute_" + "".join(random.choices(string.ascii_lowercase, k=5))
    session_id = "wsroute_" + "".join(random.choices(string.ascii_lowercase, k=8))
    client.post(f"{BASE_URL}/auth/register", json={"username": username, "password": "test12345"})
    r = client.post(f"{BASE_URL}/auth/login", data={"username": username, "password": "test12345"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    questions = [
        "帮我联网搜索一下北京今天的天气",
        "联网查一下联想最近发布了什么新品",
    ]
    all_ok = True
    for q in questions:
        resp = client.post(
            f"{BASE_URL}/chat",
            json={"question": q, "session_id": session_id, "app_type": "agent"},
            headers=headers,
        )
        ans = resp.json().get("answer", "")
        used_fallback = any(m in ans for m in FALLBACK_MARKS)
        ok = resp.status_code == 200 and len(ans.strip()) > 20 and not used_fallback
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {q}")
        print(f"       {ans[:220].replace(chr(10), ' ')}")
        all_ok = all_ok and ok

    client.close()
    print("=" * 60)
    print("结果: " + ("全部走 MCP 主搜索" if all_ok else "存在降级/异常，请查后端日志中 'builtin_web_search(降级兜底)' 行"))
    return 0 if all_ok else 2


if __name__ == "__main__":
    sys.exit(main())
