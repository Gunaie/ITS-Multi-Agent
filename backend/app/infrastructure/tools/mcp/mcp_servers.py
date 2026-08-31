"""
MCP 服务器客户端。

**历史背景与修复说明（2026-08-30）**：

1. 最初使用 `agents.mcp.MCPServerSse` + 旧版 SSE 协议端点
   (`.../WebSearch/sse`)，但阿里云百炼已从 SSE 协议全面升级为
   Streamable HTTP 协议，旧端点不再返回 SSE `endpoint` 事件，导致
   mcp sse_client 抛出 "Child exited without calling task_status.started()"
   并在启动日志中持续出现 WARNING。

2. 直接将端点切换到 `MCPServerStreamableHttp` + 新端点 (`.../WebSearch/mcp`)
   后，又遇到了 **MCP 协议版本不兼容**：agents SDK 内置的 mcp v2 库默认
   使用 `protocolVersion = 2026-07-28`，方法名也是新版 `server/discover`，
   但百炼 MCP 服务端只支持旧版 `2024-11-05` + `initialize` 流程，从而
   返回 HTTP 500 Internal Server Error。

3. 综上，这里实现了一个轻量级的自定义 MCP 客户端 `BailianWebSearchMCP`，
   直接使用 httpx2 POST 严格按百炼支持的 2024-11-05 协议完成
   initialize → notifications/initialized → tools/list → tools/call
   全流程。经验证：connect/list_tools/call_tool 均成功，agents SDK
   可直接将其作为 `Agent(mcp_servers=[...])` 注入并正确调度。
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable

from config.settings import settings


class _UnsetType:
    """Sentinel for unset values; mirrors agents.mcp.server._UNSET."""


_UNSET = _UnsetType()


class BailianWebSearchMCP:
    """
    阿里云百炼联网搜索（WebSearch）MCP 服务的兼容客户端。

    使用 **旧版 MCP 协议 2024-11-05** + Streamable HTTP 端点，完全规避
    agents/mcp v2 SDK 使用的新版 `2026-07-28` / `server/discover` 流程
    与百炼服务端之间的不兼容问题。

    接口上尽量对齐 agents SDK 的 `MCPServer` 基类，使得可以直接被
    `Agent(mcp_servers=[...])` 使用。
    """

    name: str
    cache_tools_list: bool
    cached_tools: Any  # for compat with existing code
    tool_filter: Any
    tool_meta_resolver: Any
    custom_data_extractor: Any
    # agents SDK (mcp/util.py) 在解析工具结果时会直接访问该属性，
    # 缺失会导致每次调用抛 AttributeError -> 模型反复重试直至 Max turns。
    use_structured_content: bool = False

    # ---- 可调参数（对应 agents SDK 基类同名字段） ----
    _failure_error_function: Any = _UNSET
    _require_approval: Any = None

    # ---- 内部状态 ----
    _url: str
    _headers: dict[str, str]
    _client: Any | None  # httpx2.AsyncClient | None
    _tools_list: list | None
    _cache_dirty: bool
    _next_id: int
    _error_name: str

    def __init__(
        self,
        api_key: str,
        name: str = "search_mac_client",
        url: str = "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp",
        failure_error_function: Any = _UNSET,
        require_approval: Any = None,
    ) -> None:
        self.name = name
        self._url = url
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = None
        self.cache_tools_list = True
        self.cached_tools = None
        self._tools_list = None
        self._cache_dirty = False
        self.tool_filter = None
        self.tool_meta_resolver = None
        self.custom_data_extractor = None
        self._next_id = 100
        self._error_name = name
        self._failure_error_function = failure_error_function
        self._require_approval = require_approval

    # ======================================================================
    # agents SDK 内部兼容方法（在 agents.mcp.util 中被调用）
    # ======================================================================

    def _get_failure_error_function(self, agent_failure_error_function: Any) -> Any:
        if self._failure_error_function is _UNSET:
            return agent_failure_error_function
        return self._failure_error_function

    def _get_needs_approval_for_tool(
        self, tool: Any, agent: Any
    ) -> bool | Callable[[Any, dict, str], Awaitable[bool]]:
        policy = self._require_approval
        if policy is None:
            return False
        if callable(policy):
            return policy
        if isinstance(policy, dict):
            return bool(policy.get(getattr(tool, "name", None), False))
        return bool(policy)

    # ======================================================================
    # 连接 / 资源释放
    # ======================================================================

    async def connect(self) -> None:
        """按 MCP 2024-11-05 协议执行 initialize + initialized 通知。

        含 3 次指数退避重试（1s/2s）：前 2 次失败记 INFO，第 3 次失败记 WARNING 后抛出。
        百炼 MCP 偶发抖动时自动恢复，避免直接降级到本地兜底搜索。
        """
        import asyncio
        import httpx2
        from common.infrastructure.logging.logger import logger as _logger

        max_attempts = 3
        last_err: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                # 如果存在旧 client（重试场景），先关闭
                if self._client is not None:
                    try:
                        await self._client.aclose()
                    except Exception:
                        pass
                    self._client = None

                self._client = httpx2.AsyncClient(
                    timeout=httpx2.Timeout(20.0, read=300.0),
                )

                # 1) initialize
                r = await self._client.post(
                    self._url,
                    headers={**self._headers, "Content-Type": "application/json"},
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "its-multi-agent", "version": "1.0"},
                        },
                    },
                )
                r.raise_for_status()

                # 2) notifications/initialized（202 Accepted 即可，允许失败）
                try:
                    await self._client.post(
                        self._url,
                        headers={**self._headers, "Content-Type": "application/json"},
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    )
                except Exception:
                    pass
                return  # 连接成功
            except Exception as e:
                last_err = e
                if attempt < max_attempts:
                    _logger.info(f"MCP connect attempt {attempt} failed: {e}, retrying in {attempt}s...")
                    await asyncio.sleep(attempt)  # 指数退避: 1s, 2s
                else:
                    _logger.warning(f"MCP connect attempt {attempt} failed: {e}, giving up after {max_attempts} retries")
        raise RuntimeError(f"MCP connect failed after {max_attempts} retries: {last_err}")

    async def cleanup(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    # ======================================================================
    # 工具发现 / 调用
    # ======================================================================

    async def list_tools(self, run_context: Any = None, agent: Any = None) -> list:
        from mcp import Tool as MCPTool

        if (
            self.cache_tools_list
            and self._tools_list is not None
            and not self._cache_dirty
        ):
            return list(self._tools_list)

        if self._client is None:
            raise RuntimeError(
                "MCP server not initialized. Make sure you call `connect()` first."
            )

        self._next_id += 1
        r = await self._client.post(
            self._url,
            headers={**self._headers, "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "id": self._next_id, "method": "tools/list"},
        )
        r.raise_for_status()
        tools_raw = r.json().get("result", {}).get("tools", [])
        tools: list = [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object"}),
            )
            for t in tools_raw
        ]

        self._tools_list = tools
        self._cache_dirty = False
        self.cached_tools = tools
        return list(tools)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict | None,
        meta: dict | None = None,
    ) -> Any:
        from mcp.types import CallToolResult

        if self._client is None:
            raise RuntimeError(
                "MCP server not initialized. Make sure you call `connect()` first."
            )

        self._next_id += 1
        r = await self._client.post(
            self._url,
            headers={**self._headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments or {}},
            },
        )
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            return CallToolResult(
                content=[{"type": "text", "text": f"MCP错误: {data['error']}"}],
                isError=True,
            )

        result = data.get("result", {})
        return CallToolResult(
            content=result.get("content", []),
            isError=result.get("isError", False),
        )


# ==========================================================================
# 百度地图 MCP 客户端
# ==========================================================================

# 说明：百度地图官方并未在百炼 MCP 平台上提供标准 MCP 端点；
# 为了将其作为 MCP 接入到 agents SDK 的 Agent.mcp_servers 管道中，
# 这里继续使用"鸭子类型 MCP 服务"模式，把已验证稳定的本地 REST 封装
# (baidu_map_tool) 重新包装成标准 MCP tool -> call_tool 流程。
# 这样既可保留 agents SDK 对 mcp_servers 的统一调度/审批/错误处理，
# 又严格只使用用户提供的百度地图 AK，不涉及任何高德相关代码。

class BaiduMapMCP:
    """
    百度地图 REST API 的 MCP 兼容包装器。

    暴露 3 个 MCP 工具：
      1) baidu_geocode: address -> "lat,lng"
      2) baidu_place_search: 周边/关键词 POI 搜索
      3) baidu_driving_routematrix: 批量驾车路网距离 (km)
    """

    name: str
    cache_tools_list: bool
    cached_tools: Any
    tool_filter: Any
    tool_meta_resolver: Any
    custom_data_extractor: Any
    # 同 BailianWebSearchMCP：SDK 硬访问该属性，必须提供
    use_structured_content: bool = False

    _failure_error_function: Any = _UNSET
    _require_approval: Any = None

    _ak: str | None
    _tools_list: list | None
    _cache_dirty: bool
    _error_name: str

    def __init__(
        self,
        ak: str,
        name: str = "baidu_map_mcp",
        failure_error_function: Any = _UNSET,
        require_approval: Any = None,
    ) -> None:
        self.name = name
        self._ak = ak
        self.cache_tools_list = True
        self.cached_tools = None
        self._tools_list = None
        self._cache_dirty = False
        self.tool_filter = None
        self.tool_meta_resolver = None
        self.custom_data_extractor = None
        self._error_name = name
        self._failure_error_function = failure_error_function
        self._require_approval = require_approval

    # ---- agents SDK 内部兼容方法 ----
    def _get_failure_error_function(self, agent_failure_error_function: Any) -> Any:
        if self._failure_error_function is _UNSET:
            return agent_failure_error_function
        return self._failure_error_function

    def _get_needs_approval_for_tool(
        self, tool: Any, agent: Any
    ) -> bool | Callable[[Any, dict, str], Awaitable[bool]]:
        policy = self._require_approval
        if policy is None:
            return False
        if callable(policy):
            return policy
        if isinstance(policy, dict):
            return bool(policy.get(getattr(tool, "name", None), False))
        return bool(policy)

    # ---- 连接 / 资源释放 ----
    async def connect(self) -> None:
        """百度地图 REST 是无状态 HTTP，无长连接。

        惰性校验：不预热消耗配额，AK 合法性留给首次真实调用验证。
        仅检查 AK 配置是否存在；connect 失败不阻断启动，让 service_agent
        退化到本地 DB 兜底查询（service_stations 表已存在）。
        """
        from common.infrastructure.logging.logger import logger as _logger
        if not self._ak:
            _logger.warning("BAIDU_MAP_AK 未配置，百度地图工具不可用，service_agent 将退化到本地 DB 兜底")
            # 不抛异常，让上层继续启动
            return
        _logger.info("BaiduMapMCP: AK 已配置，采用惰性校验（首次真实调用时验证 AK 有效性）")

    async def cleanup(self) -> None:
        # 不主动关闭共享的 baidu_map_tool client，避免打断其他工具
        pass

    # ---- 工具发现 / 调用 ----
    async def list_tools(self, run_context: Any = None, agent: Any = None) -> list:
        from mcp import Tool as MCPTool

        if (
            self.cache_tools_list
            and self._tools_list is not None
            and not self._cache_dirty
        ):
            return list(self._tools_list)

        tools = [
            MCPTool(
                name="baidu_geocode",
                description=(
                    "百度地图地理编码：将中文地址/地名转换为经纬度坐标。"
                    "入参 address 为地址文本（如：武汉市洪山区武汉工程大学）；"
                    "返回形如『lat,lng』的字符串（BD-09 坐标系）。"
                    "找不到结果时返回空字符串。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "string",
                            "description": "要查询的中文地址或地名",
                        }
                    },
                    "required": ["address"],
                },
            ),
            MCPTool(
                name="baidu_place_search",
                description=(
                    "百度地图 POI 周边搜索：按经纬度中心点 + 关键词 + 半径查找周边"
                    "POI（如维修站、加油站、银行、餐厅等）。返回列表含 name、address、"
                    "tel、lat、lng、distance(米) 字段。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "coords": {
                            "type": "string",
                            "description": "中心点坐标，格式：lat,lng",
                        },
                        "keywords": {
                            "type": "string",
                            "description": "POI 关键词，如：联想维修站、招商银行",
                        },
                        "radius": {
                            "type": "integer",
                            "description": "搜索半径（米），默认 50000",
                            "default": 50000,
                        },
                    },
                    "required": ["coords", "keywords"],
                },
            ),
            MCPTool(
                name="baidu_driving_routematrix",
                description=(
                    "百度地图批量驾车路网距离计算：给定一个起点（lat,lng）和多个终点，"
                    "返回每条路径的驾车路网距离（公里）。"
                    "百度 API 限制最多 50 个终点。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "string",
                            "description": "起点坐标：lat,lng",
                        },
                        "destinations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "终点坐标列表，如：[\"lat1,lng1\", \"lat2,lng2\"]",
                        },
                    },
                    "required": ["origin", "destinations"],
                },
            ),
        ]
        self._tools_list = tools
        self._cache_dirty = False
        self.cached_tools = tools
        return list(tools)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict | None,
        meta: dict | None = None,
    ) -> Any:
        from mcp.types import CallToolResult
        from infrastructure.tools.local.baidu_map_tool import (
            baidu_geocode,
            baidu_around_search,
            baidu_get_distances_batch,
        )

        args = arguments or {}
        try:
            if tool_name == "baidu_geocode":
                address = args.get("address", "")
                coords = await baidu_geocode(address)
                text = coords or "(未找到匹配坐标)"
                return CallToolResult(
                    content=[{"type": "text", "text": str(text)}],
                    isError=not bool(coords),
                )

            if tool_name == "baidu_place_search":
                coords = args.get("coords", "")
                keywords = args.get("keywords", "")
                radius = int(args.get("radius", 50000))
                pois = await baidu_around_search(coords, keywords, radius=radius)
                import json as _json
                text = _json.dumps(pois, ensure_ascii=False)
                return CallToolResult(
                    content=[{"type": "text", "text": text}],
                    isError=False,
                )

            if tool_name == "baidu_driving_routematrix":
                origin = args.get("origin", "")
                destinations = args.get("destinations", []) or []
                dists = await baidu_get_distances_batch(origin, destinations)
                import json as _json
                text = _json.dumps(
                    {"distances_km": dists},
                    ensure_ascii=False,
                )
                return CallToolResult(
                    content=[{"type": "text", "text": text}],
                    isError=False,
                )

            return CallToolResult(
                content=[
                    {
                        "type": "text",
                        "text": f"BaiduMapMCP: 未识别的工具名 {tool_name}",
                    }
                ],
                isError=True,
            )
        except Exception as e:
            return CallToolResult(
                content=[{"type": "text", "text": f"BaiduMapMCP 调用异常: {e}"}],
                isError=True,
            )


# ==========================================================================
# 全局单例（替换原 search_mac_client / baidu_map_mcp）
# ==========================================================================

# 若未配置 API Key，则退化为 None，启动时不会再报连接 WARNING
if settings.AL_BAILIAN_API_KEY and not settings.AL_BAILIAN_API_KEY.startswith(
    "your_"
):
    search_mac_client: BailianWebSearchMCP | None = BailianWebSearchMCP(
        api_key=settings.AL_BAILIAN_API_KEY,
        name="search_mac_client",
    )
else:
    search_mac_client = None


# 百度地图 MCP：同样仅在 AK 有效时初始化
if settings.BAIDU_MAP_AK and not settings.BAIDU_MAP_AK.startswith("your_"):
    baidu_map_mcp: BaiduMapMCP | None = BaiduMapMCP(
        ak=settings.BAIDU_MAP_AK,
        name="baidu_map_mcp",
    )
else:
    baidu_map_mcp = None
