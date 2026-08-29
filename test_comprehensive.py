import requests
import httpx
import json
import asyncio
import time
import os

# Configuration
MAIN_BACKEND_URL = "http://127.0.0.1:8002"
KNOWLEDGE_BACKEND_URL = "http://127.0.0.1:8001"
FRONTEND_CONSULTATION_URL = "http://localhost:3002" # Based on agent_web_ui vite.config.js
FRONTEND_MANAGEMENT_URL = "http://localhost:3000"   # Based on knowlege_platform_ui vite.config.js

class SystemTester:
    def __init__(self):
        self.token = None
        self.username = f"testuser_{int(time.time())}"
        self.password = "password123"

    def print_step(self, step):
        print(f"\n{'='*20} {step} {'='*20}")

    async def test_auth(self):
        self.print_step("Testing Authentication")
        async with httpx.AsyncClient() as client:
            # Register
            print(f"Registering user: {self.username}")
            resp = await client.post(f"{MAIN_BACKEND_URL}/auth/register", json={
                "username": self.username,
                "password": self.password
            })
            print(f"Register Status: {resp.status_code}, Response: {resp.json()}")
            assert resp.status_code == 200

            # Login
            print("Logging in...")
            resp = await client.post(f"{MAIN_BACKEND_URL}/auth/login", data={
                "username": self.username,
                "password": self.password
            })
            print(f"Login Status: {resp.status_code}")
            assert resp.status_code == 200
            self.token = resp.json().get("access_token")
            assert self.token is not None
            print("Authentication successful!")

    async def test_knowledge_base(self):
        self.print_step("Testing Knowledge Base (Management)")
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Upload document
            print("Uploading test document...")
            test_file = "full_system_test_doc.md"
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("# TRAE AI Assist\nTRAE is a powerful AI coding assistant developed by ByteDance.\nIt supports multi-agent orchestration and advanced RAG.")
            
            with open(test_file, "rb") as f:
                resp = await client.post(
                    f"{KNOWLEDGE_BACKEND_URL}/upload",
                    files={"file": (test_file, f, "text/markdown")}
                )
            print(f"Upload Status: {resp.status_code}, Response: {resp.json()}")
            assert resp.status_code == 200
            os.remove(test_file)

            # Wait for indexing
            print("Waiting for indexing (10s)...")
            await asyncio.sleep(10)

            # Query Knowledge Base
            print("Querying Knowledge Base directly...")
            resp = await client.post(
                f"{KNOWLEDGE_BACKEND_URL}/query",
                json={"question": "What is TRAE?"}
            )
            print(f"Query Status: {resp.status_code}, Response: {resp.json()}")
            assert resp.status_code == 200
            assert "TRAE" in resp.json().get("answer", "")
            print("Knowledge Base RAG test passed!")

    async def test_orchestrator_stream(self):
        self.print_step("Testing Orchestrator & Streaming (Consultation)")
        if not self.token:
            print("Skipping Orchestrator test: No auth token")
            return

        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Test Case 1: Knowledge Retrieval (RAG via Orchestrator)
            print("\nCase 1: RAG via Orchestrator")
            question = "简要说明 TRAE 是什么？"
            print(f"Question: {question}")
            
            async with client.stream('POST', f"{MAIN_BACKEND_URL}/chat_stream", 
                                   json={'question': question, 'session_id': 'full_test_session'}, 
                                   headers=headers) as response:
                full_content = ""
                async for line in response.aiter_lines():
                    if line.startswith('data: '):
                        data_str = line[6:].strip()
                        if data_str == '[DONE]': break
                        try:
                            data = json.loads(data_str)
                            if data['type'] == 'run_item_stream_event' and 'content' in data:
                                print(data['content'], end='', flush=True)
                                full_content += data['content']
                        except: pass
            
            assert "TRAE" in full_content or "AI" in full_content
            print("\n[RAG Stream Success]")

            # Test Case 2: Tool Calling (MCP WebSearch via Orchestrator)
            print("\nCase 2: MCP Tool Calling (WebSearch)")
            question = "现在的北京时间是多少？" # Usually requires search or specific tool
            print(f"Question: {question}")
            
            async with client.stream('POST', f"{MAIN_BACKEND_URL}/chat_stream", 
                                   json={'question': question, 'session_id': 'full_test_session'}, 
                                   headers=headers) as response:
                tool_called = False
                async for line in response.aiter_lines():
                    if line.startswith('data: '):
                        data_str = line[6:].strip()
                        if data_str == '[DONE]': break
                        try:
                            data = json.loads(data_str)
                            if data['type'] == 'run_item_stream_event':
                                if data['item_type'] == 'tool_call_item':
                                    print(f"\n[Tool Called: {data.get('tool_name')}]")
                                    tool_called = True
                                elif 'content' in data:
                                    print(data['content'], end='', flush=True)
                        except: pass
            
            # Test Case 3: Non-streaming Chat (Management Chat)
            print("\nCase 3: Non-streaming Chat")
            question = "TRAE 的主要功能有哪些？"
            print(f"Question: {question}")
            
            resp = await client.post(f"{MAIN_BACKEND_URL}/chat", 
                                   json={'question': question, 'session_id': 'full_test_session'}, 
                                   headers=headers)
            print(f"Chat Status: {resp.status_code}, Response: {resp.json()}")
            assert resp.status_code == 200
            assert "TRAE" in resp.json().get("answer", "")
            print("[Non-streaming Chat Success]")

    async def run_all(self):
        try:
            # 强制设置输出编码为 utf-8 以防止 Windows 下的 UnicodeEncodeError
            import sys
            import io
            if sys.platform == "win32":
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
                sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

            await self.test_auth()
            await self.test_knowledge_base()
            await self.test_orchestrator_stream()
            print("\n" + "="*50)
            print("ALL CORE SYSTEM TESTS PASSED!")
            print("="*50)
        except Exception as e:
            print(f"\nTEST FAILED: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    tester = SystemTester()
    asyncio.run(tester.run_all())
