from typing import List
from langchain_core.embeddings import Embeddings
import httpx
import logging

logger = logging.getLogger(__name__)

class DashScopeEmbeddings(Embeddings):
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
        # 统一使用 OpenAI 兼容模式端点，支持 v1/v2/v3 以及 Bailian 上的模型
        self.url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        logger.info(f"Initialized DashScopeEmbeddings with model: {model} using compatible-mode URL")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        all_embeddings = []
        batch_size = 10  # DashScope 限制单次请求最多 10 条
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # DashScope 标准 API 的格式与 OpenAI 不同
            # 如果是兼容模式 URL
            if "compatible-mode" in self.url:
                payload = {
                    "model": self.model,
                    "input": batch
                }
            else:
                payload = {
                    "model": self.model,
                    "input": {
                        "texts": batch
                    }
                }

            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(self.url, json=payload, headers=headers)
                    if response.status_code != 200:
                        logger.error(f"DashScope API Error: {response.status_code} - {response.text}")
                        # 尝试切换模型名 (有些环境需要前缀，有些不需要)
                        if response.status_code == 404:
                            alternative_model = "text-embedding-v3" if self.model != "text-embedding-v3" else "BAAI/bge-m3"
                            logger.info(f"Trying alternative model: {alternative_model}")
                            payload["model"] = alternative_model
                            response = client.post(self.url, json=payload, headers=headers)
                    
                    if response.status_code != 200:
                         # 如果还是失败，抛出带详细信息的异常
                         raise Exception(f"DashScope API failed after retry: {response.status_code} - {response.text}")

                    response.raise_for_status()
                    result = response.json()
                    
                    if "compatible-mode" in self.url:
                        embeddings = [item["embedding"] for item in result["data"]]
                    else:
                        embeddings = [item["embedding"] for item in result["output"]["embeddings"]]
                    
                    all_embeddings.extend(embeddings)
            except Exception as e:
                logger.error(f"DashScope embed_documents batch {i//batch_size} failed: {e}")
                raise e
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # 处理不同的 API 格式
        if "compatible-mode" in self.url:
            payload = {
                "model": self.model,
                "input": [text]
            }
        else:
            payload = {
                "model": self.model,
                "input": {
                    "texts": [text]
                }
            }
            
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(self.url, json=payload, headers=headers)
                
                if response.status_code != 200:
                    logger.error(f"DashScope embed_query Error: {response.status_code} - {response.text}")
                    # 尝试切换模型名
                    if response.status_code == 404:
                        alternative_model = "text-embedding-v3" if self.model != "text-embedding-v3" else "BAAI/bge-m3"
                        logger.info(f"Trying alternative model in embed_query: {alternative_model}")
                        payload["model"] = alternative_model
                        response = client.post(self.url, json=payload, headers=headers)
                
                if response.status_code != 200:
                     raise Exception(f"DashScope embed_query failed after retry: {response.status_code} - {response.text}")

                response.raise_for_status()
                result = response.json()
                
                if "compatible-mode" in self.url:
                    embedding = result["data"][0]["embedding"]
                else:
                    embedding = result["output"]["embeddings"][0]["embedding"]
                return embedding
        except Exception as e:
            logger.error(f"DashScope embed_query failed: {e}")
            raise e
