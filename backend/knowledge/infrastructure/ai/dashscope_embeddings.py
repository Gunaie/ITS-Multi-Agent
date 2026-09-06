from typing import List
from langchain_core.embeddings import Embeddings
import httpx
import logging
import time

logger = logging.getLogger(__name__)

# 网络类故障（DNS 解析失败、连接超时、5xx）时的重试次数与退避
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 2)


class DashScopeEmbeddings(Embeddings):
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
        # 统一使用 OpenAI 兼容模式端点，支持 v1/v2/v3 以及 Bailian 上的模型
        self.url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        logger.info(f"Initialized DashScopeEmbeddings with model: {model} using compatible-mode URL")

    def _post_with_retry(self, payload: dict, headers: dict) -> dict:
        """
        发起 DashScope embedding 请求，对网络类故障（DNS 解析失败、连接超时、
        5xx 服务端错误）做有限次重试；404 时按原逻辑切换备选模型。
        """
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(self.url, json=payload, headers=headers)

                    if response.status_code == 404:
                        # 尝试切换模型名 (有些环境需要前缀，有些不需要)
                        alternative_model = "text-embedding-v3" if payload.get("model") != "text-embedding-v3" else "BAAI/bge-m3"
                        logger.info(f"Trying alternative model: {alternative_model}")
                        payload = dict(payload)
                        payload["model"] = alternative_model
                        response = client.post(self.url, json=payload, headers=headers)

                    if response.status_code != 200:
                        # 5xx 服务端错误可重试；4xx（除404已处理）直接失败
                        if 500 <= response.status_code < 600 and attempt < MAX_RETRIES:
                            logger.warning(
                                f"DashScope API {response.status_code}，第 {attempt} 次请求失败，"
                                f"{RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]}s 后重试"
                            )
                            time.sleep(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])
                            continue
                        raise Exception(f"DashScope API failed: {response.status_code} - {response.text}")

                    return response.json()
            except (httpx.RequestError, httpx.HTTPError) as e:
                # DNS 解析失败、连接超时等网络层故障：重试
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
                    logger.warning(f"DashScope 网络故障({e})，第 {attempt} 次请求失败，{wait}s 后重试")
                    time.sleep(wait)
                    continue
                logger.error(f"DashScope 请求重试 {MAX_RETRIES} 次后仍失败: {e}")
                raise
        raise Exception(f"DashScope 请求失败: {last_error}")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        all_embeddings = []
        batch_size = 10  # DashScope 限制单次请求最多 10 条

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # 统一使用兼容模式 payload
            payload = {
                "model": self.model,
                "input": batch
            }

            try:
                result = self._post_with_retry(payload, headers)
                embeddings = [item["embedding"] for item in result["data"]]
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

        payload = {
            "model": self.model,
            "input": [text]
        }

        try:
            result = self._post_with_retry(payload, headers)
            return result["data"][0]["embedding"]
        except Exception as e:
            logger.error(f"DashScope embed_query failed: {e}")
            raise e
