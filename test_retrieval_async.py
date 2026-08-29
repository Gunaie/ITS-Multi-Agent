import asyncio
import os
import sys

# Add backend/knowledge to path
sys.path.append(os.path.join(os.getcwd(), "backend", "knowledge"))
sys.path.append(os.path.join(os.getcwd(), "backend"))

from backend.knowledge.services.retrieval_service import RetrievalService

async def test():
    service = RetrievalService()
    question = "我的电脑开机之后没有任何的反应"
    print(f"Testing retrieval for: {question}")
    docs = await service.retrieval(question)
    print(f"Found {len(docs)} documents.")
    for doc in docs:
        print(f"- Title: {doc.metadata.get('title')}, Score: {doc.metadata.get('similarity', 'N/A')}")

if __name__ == "__main__":
    asyncio.run(test())
