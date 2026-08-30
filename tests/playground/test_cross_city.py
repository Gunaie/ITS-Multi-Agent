import asyncio
import requests
import json
import sys

BASE_URL = "http://127.0.0.1:8002"

async def test_cross_city_query():
    print("\n--- Testing Cross-City Service Station Query (Shanghai) ---")
    
    # 1. 注册并登录
    username = "test_shanghai_user"
    password = "password123"
    requests.post(f"{BASE_URL}/auth/register", json={"username": username, "password": password})
    login_resp = requests.post(f"{BASE_URL}/auth/login", data={"username": username, "password": password})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. 模拟在上海的查询
    # 我们直接在 question 中提到上海，或者通过 location 参数传递上海坐标
    # 上海坐标大约是: 31.2304, 121.4737
    chat_data = {
        "question": "我在上海，附近哪里有联想维修站？",
        "session_id": "test_session_sh",
        "location": "31.2304,121.4737"
    }
    
    print(f"Querying: {chat_data['question']} with location {chat_data['location']}")
    response = requests.post(f"{BASE_URL}/chat", json=chat_data, headers=headers)
    
    if response.status_code == 200:
        answer = response.json()["answer"]
        print(f"\nAgent Answer:\n{answer}")
        if "上海" in answer and "联想" in answer:
            print("\n✅ Cross-city query successful!")
        else:
            print("\n❌ Unexpected answer content.")
    else:
        print(f"\n❌ Request failed: {response.text}")

if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    asyncio.run(test_cross_city_query())
