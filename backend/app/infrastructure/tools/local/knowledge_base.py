import httpx
from agents import function_tool
from config.settings import settings
from common.infrastructure.logging.logger import logger

@function_tool
async def query_knowledge(question: str) -> str:
    """
    查询 ITS 知识库以获取技术支持信息。
    当用户询问关于联想产品、系统安装、故障排除等技术问题时使用此工具。
    
    Args:
        question: 用户的问题
        
    Returns:
        str: 知识库返回的解答内容
    """
    url = f"{settings.KNOWLEDGE_BASE_URL}/query"
    payload = {"question": question}
    
    try:
        # 120s: 知识库 /query 包含 RAG 生成(现为思考模型 qwen3.7-max-2026-05-20),
        # 复杂问题生成可超 60s,实测 60s 会 ReadTimeout 导致技术专家走兜底
        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.info(f"Querying knowledge base at {url} with question: {question}")
            response = await client.post(url, json=payload)
            logger.info(f"Knowledge base response status: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            answer = result.get("answer", "未能从知识库中找到相关信息。")
            logger.info(f"Knowledge base returned answer of length {len(answer)}")
            return answer
    except Exception as e:
        logger.error(f"调用知识库 API 失败: {str(e)}", exc_info=True)
        return f"查询知识库时发生错误: {str(e)}"
