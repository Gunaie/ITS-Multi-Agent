import httpx
import json
import asyncio
import time

async def test_stream():
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            username = f"testuser_{int(time.time())}"
            password = "password123"
            
            # Register
            print(f"Registering user {username}...")
            await client.post('http://localhost:8002/auth/register', json={'username': username, 'password': password})
            
            # Login
            print("Logging in...")
            resp = await client.post('http://localhost:8002/auth/login', data={'username': username, 'password': password})
            token = resp.json()['access_token']
            headers = {'Authorization': f'Bearer {token}'}
            
            # Test cases: one for knowledge, one for tool calling (WebSearch)
            test_cases = [
                "联想智能电视有什么特点？",  # RAG
                "今天北京的天气怎么样？",    # WebSearch / Tool
            ]
            
            for question in test_cases:
                print(f"\n\nQuestion: {question}")
                print("-" * 50)
                async with client.stream('POST', 'http://localhost:8002/chat_stream', 
                                       json={'question': question, 'session_id': 'test_session'}, 
                                       headers=headers) as response:
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            data_str = line[6:].strip()
                            if not data_str:
                                continue
                            if data_str == '[DONE]':
                                print("\n[Stream finished]")
                                break
                            try:
                                data = json.loads(data_str)
                                if data['type'] == 'run_item_stream_event':
                                    if data['item_type'] == 'message_output_item':
                                        if 'reasoning_content' in data:
                                            print(f"\n[Reasoning]: {data['reasoning_content']}", end='', flush=True)
                                        if 'content' in data:
                                            print(data['content'], end='', flush=True)
                                    elif data['item_type'] == 'tool_call_item':
                                        print(f"\n[Calling Tool: {data.get('tool_name')}]")
                                    elif data['item_type'] == 'tool_call_output_item':
                                        print(f"\n[Tool Output received]")
                                elif data['type'] == 'agent_updated_stream_event':
                                    print(f"\n[Switching to Agent: {data['new_agent']}]\n")
                                elif data['type'] == 'error':
                                    print(f"\n[Error]: {data.get('message')}")
                            except Exception as e:
                                print(f"\nError parsing SSE: {e} | Data: {data_str}")
            
        except Exception as e:
            print(f"\nError during test: {e}")

if __name__ == "__main__":
    asyncio.run(test_stream())
