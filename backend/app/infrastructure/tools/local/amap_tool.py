
import httpx
from agents import function_tool, RunContextWrapper
from config.settings import settings
from common.infrastructure.logging.logger import logger

@function_tool
async def bailian_amap_search(ctx: RunContextWrapper, query: str) -> str:
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
    
    # 尝试从上下文中获取位置信息，增强搜索精度
    session = ctx.context
    location = None
    if session and hasattr(session, 'context'):
        location = session.context.get("user_location")
    
    # 构造百炼插件调用的标准 Payload
    payload = {
        "model": "qwen-plus",
        "messages": [
            {
                "role": "user",
                "content": f"请帮我查询附近的 {query}。当前坐标为：{location or '北京市中心'}"
            }
        ],
        "plugins": {
            "amap_maps": {}
        }
    }
    
    try:
        if not api_key or api_key.startswith("sk-your-key"):
             return "未检测到有效的 AL_BAILIAN_API_KEY，无法使用高德地图服务。"

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 使用百炼统一的 Chat 接口驱动插件
            url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
            headers["X-DashScope-Plugin"] = "amap_maps" # 关键请求头
            
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                # 提取插件返回的真实地点信息
                text = data.get("output", {}).get("text")
                if text and "抱歉" not in text and "无法" not in text:
                    return f"【高德地图实时数据】\n{text}"
                
                # 如果插件返回了结构化数据但没有 text，尝试提取
                choices = data.get("output", {}).get("choices", [])
                if choices:
                    plugin_content = choices[0].get("message", {}).get("content", "")
                    if plugin_content:
                        return f"【高德地图实时数据】\n{plugin_content}"
            
            logger.warning(f"高德地图 API 未能返回有效结果: {response.text}")
            
        # 终极兜底：如果 API 失败或结果不理想，尝试用联网搜索工具代为查询
        search_query = f"{location or ''} {query} 地址 电话"
        search_result = await bailian_web_search.__wrapped__(search_query)
        if search_result and "抱歉" not in search_result:
            return f"【联网搜索数据】\n{search_result}"
            
        return f"在线地图服务暂时繁忙。建议您直接点击此处：[高德地图搜索 {query}](https://www.amap.com/search?query={query})"
    except Exception as e:
        logger.error(f"高德地图工具执行失败: {str(e)}")
        return f"地图服务连接超时，请稍后再试。"
