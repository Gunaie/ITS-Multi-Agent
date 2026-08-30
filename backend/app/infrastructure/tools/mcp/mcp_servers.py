from agents.mcp import MCPServerSse
from config.settings import settings

# 阿里百炼联网搜索 MCP 服务
search_mac_client = MCPServerSse(
    params={
        "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse",
        "headers": {
            "Authorization": f"Bearer {settings.AL_BAILIAN_API_KEY}",
            "X-DashScope-SSE": "enable",
            "Accept": "text/event-stream"
        }
    },
    name="search_mac_client"
)

# 为了兼容旧代码中的 baidu_map_mcp 引用
baidu_map_mcp = None
