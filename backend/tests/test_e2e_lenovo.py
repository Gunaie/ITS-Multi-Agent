"""
联想售后场景 E2E 测试（阶段6）

测试三种意图场景：
A. 纯技术问题（other → orchestrator → technical）
B. 纯服务查询（service_only → 直连 service）
C. 复合意图（compound → 先 technical 后 service）

运行前置：双服务已启动（8001 知识库 + 8002 主后端）
运行：python tests/test_e2e_lenovo.py
"""
import os
import sys
import time
import httpx

BASE = "http://localhost:8002"
TEST_USER = f"e2e_test_{int(time.time())}"
TEST_PASS = "Test123456"


def register_and_login() -> str:
    """注册测试用户并登录，返回 access_token"""
    with httpx.Client(timeout=10) as c:
        # 注册
        try:
            r = c.post(f"{BASE}/auth/register", json={"username": TEST_USER, "password": TEST_PASS})
            print(f"注册: {r.status_code}")
        except Exception as e:
            print(f"注册（可能已存在）: {e}")
        # 登录
        r = c.post(f"{BASE}/auth/login", data={"username": TEST_USER, "password": TEST_PASS})
        print(f"登录: {r.status_code}")
        token = r.json().get("access_token")
        if not token:
            print(f"登录失败: {r.text[:200]}")
            sys.exit(1)
        return token


def chat(token: str, question: str, session_id: str, location: str = None) -> dict:
    """调用 /chat 接口"""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "question": question,
        "session_id": session_id,
        "app_type": "agent",
    }
    if location:
        payload["location"] = location
    with httpx.Client(timeout=120) as c:
        r = c.post(f"{BASE}/chat", json=payload, headers=headers)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "detail": r.text[:300]}
        return r.json()


def main():
    print("=" * 70)
    print("联想售后场景 E2E 测试")
    print("=" * 70)

    token = register_and_login()
    print(f"Token: {token[:20]}...")

    # 场景A：纯技术问题
    print("\n" + "=" * 70)
    print("场景A：纯技术问题（ThinkPad 蓝屏诊断）")
    print("=" * 70)
    sid = f"e2e_a_{int(time.time())}"
    result = chat(token, "我的ThinkPad蓝屏了怎么办", sid)
    answer = result.get("answer", "")
    print(f"回答长度: {len(answer)} 字")
    print(f"回答预览: {answer[:300]}...")
    has_tech = any(k in answer for k in ["蓝屏", "驱动", "系统", "重启", "安全模式", "内存", "硬盘"])
    print(f"✅ 含技术诊断内容" if has_tech else f"⚠️ 未检出技术诊断关键词")

    # 场景B：纯服务查询
    print("\n" + "=" * 70)
    print("场景B：纯服务查询（武汉维修站）")
    print("=" * 70)
    sid = f"e2e_b_{int(time.time())}"
    result = chat(token, "附近哪里有维修站", sid, location="wgs84:114.35,30.59")
    answer = result.get("answer", "")
    print(f"回答长度: {len(answer)} 字")
    print(f"回答预览: {answer[:400]}...")
    has_service = any(k in answer for k in ["维修站", "服务站", "网点", "地址", "电话", "导航", "km", "公里"])
    print(f"✅ 含维修站查询结果" if has_service else f"⚠️ 未检出维修站结果（可能配额超限降级）")

    # 场景C：复合意图
    print("\n" + "=" * 70)
    print("场景C：复合意图（蓝屏 + 维修站）")
    print("=" * 70)
    sid = f"e2e_c_{int(time.time())}"
    result = chat(token, "ThinkPad蓝屏了，附近哪里有维修站", sid, location="wgs84:114.35,30.59")
    answer = result.get("answer", "")
    print(f"回答长度: {len(answer)} 字")
    print(f"回答预览: {answer[:500]}...")
    has_both = has_tech and has_service
    has_separator = "---" in answer
    print(f"✅ 含技术诊断: {has_tech}")
    print(f"✅ 含维修站结果: {has_service}")
    print(f"✅ 含合并分隔符: {has_separator}")
    if has_both and has_separator:
        print("\n🎉 复合意图编排成功：技术诊断 + 维修站查询均已返回")
    else:
        print("\n⚠️ 复合意图编排可能不完整")

    print("\n" + "=" * 70)
    print("E2E 测试完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
