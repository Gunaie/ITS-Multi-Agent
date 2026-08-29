import httpx
import json
import asyncio

async def test():
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # Try to login
            print("Attempting login...")
            resp = await client.post('http://localhost:8002/auth/login', data={'username': 'testuser', 'password': 'password'})
            print(f"Login status: {resp.status_code}")
            
            if resp.status_code != 200:
                print("Login failed, attempting register...")
                resp = await client.post('http://localhost:8002/auth/register', json={'username': 'testuser', 'password': 'password'})
                print(f"Register status: {resp.status_code}")
                
                print("Attempting login again...")
                resp = await client.post('http://localhost:8002/auth/login', data={'username': 'testuser', 'password': 'password'})
                print(f"Login 2 status: {resp.status_code}")
            
            if resp.status_code == 200:
                token = resp.json()['access_token']
                headers = {'Authorization': f'Bearer {token}'}
                print("Attempting chat...")
                resp = await client.post('http://localhost:8002/chat', json={'question': '你好', 'session_id': 'test'}, headers=headers)
                print(f"Chat status: {resp.status_code}")
                print(f"Chat response: {resp.text}")
            else:
                print(f"Final login failed: {resp.text}")
                
        except Exception as e:
            print(f"Error during test: {e}")

if __name__ == "__main__":
    asyncio.run(test())
