import httpx
import json

url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
api_key = "sk-e835f544a996476eb0393c3d430a8008"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}
payload = {
    "model": "text-embedding-v3",
    "input": ["测试一下"]
}

response = httpx.post(url, json=payload, headers=headers)
print(f"Status: {response.status_code}")
print(f"Body: {response.text}")
