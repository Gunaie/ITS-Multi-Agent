
import httpx
from agents import function_tool
from config.settings import settings
from common.infrastructure.logging.logger import logger

@function_tool
async def bailian_amap_search(query: str) -> str:
    """
    使用高德地图服务查询地点、周边设施、路线规划或地理编码信息。
    当用户提到“哪里有”、“怎么去”、“最近的...在哪里”或查询特定位置时，必须使用此工具。
    
    Args:
        query: 搜索关键词或位置描述
        
    Returns:
        str: 地图搜索结果摘要
    """
    api_key = settings.AL_BAILIAN_API_KEY
    # 高德地图在百炼上的工具调用通常也是通过统一的 API 接口
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/amap-maps/search"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "qwen-plus",
        "input": {
            "query": query
        }
    }
    
    try:
        if not api_key or api_key.startswith("sk-your-key"):
             return "未检测到有效的 AL_BAILIAN_API_KEY，无法使用高德地图服务。"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                text = data.get("output", {}).get("text")
                if text:
                    return f"【高德地图】{text}"
            else:
                logger.warning(f"高德地图 API 返回错误: {response.status_code} - {response.text}")
                
        # Fallback 逻辑
        return f"抱歉，高德地图在线服务目前响应较慢。您可以尝试访问高德地图官网或 App 查询 '{query}'。"
    except Exception as e:
        logger.error(f"高德地图工具执行失败: {str(e)}")
        return f"地图服务连接超时，请稍后再试。"
