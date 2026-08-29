import httpx
from agents import function_tool
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("answer", "未能从知识库中找到相关信息。")
    except Exception as e:
        logger.error(f"调用知识库 API 失败: {str(e)}")
        return f"查询知识库时发生错误: {str(e)}"
