from agents.memory import SessionABC
from agents.items import TResponseInputItem
from typing import List, Optional

# 调度者自己的交接工具名。
# 背景: 多轮对话时, 调度者若在历史中看到子专家的工具调用记录, 会模仿着直接调用
# 自己没有的工具, 触发 ModelBehaviorError -> HTTP 500。
# 因此喂给模型的历史需要剥离子专家的工具条目; 但**调度者自己的交接记录必须保留**——
# 否则多轮之后调度者会"忘记"自己此前是如何处理服务请求的（交接行为在历史中不可见）,
# temperature=0 下它会转而模仿历史中可见的文本模式（复读追问文案/嘴上说转接却不调工具）。
_HANDOFF_TOOL_NAMES = {"consult_technical_expert", "query_service_station_and_navigate"}

# 从"持久化历史"中剥离的工具类条目类型（子专家的工具与推理过程）。
_TOOL_HISTORY_TYPES = {
    "function_call",
    "function_call_output",
    "tool_call",
    "tool_call_output",
    "hosted_tool_call",
    "hosted_tool_call_output",
    "web_search_call",
    "reasoning",
}


def _get_field(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _item_type(item) -> Optional[str]:
    return _get_field(item, "type")


def _is_handoff_call(item) -> bool:
    """是否为调度者自己的交接调用条目（这类条目要保留在历史中）。"""
    if _item_type(item) not in ("function_call", "tool_call"):
        return False
    return _get_field(item, "name") in _HANDOFF_TOOL_NAMES


def _is_tool_history_item(item, handoff_call_ids: set) -> bool:
    t = _item_type(item)
    if t in ("function_call", "tool_call"):
        # 调度者自己的交接调用 -> 保留; 其余工具调用 -> 剥离
        return not _is_handoff_call(item)
    if t in ("function_call_output", "tool_call_output"):
        # 与交接调用配对的输出 -> 保留; 其余 -> 剥离
        call_id = _get_field(item, "call_id")
        return call_id not in handoff_call_ids
    if t in _TOOL_HISTORY_TYPES:
        return True
    role = _get_field(item, "role")
    if role == "assistant":
        calls = _get_field(item, "tool_calls")
        if calls:
            return True
    return False


class SimpleSession(SessionABC):
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.items: List[TResponseInputItem] = []
        self._context: dict = {}

    def __setstate__(self, state):
        """确保从 Redis 反序列化时能平稳处理类定义的变动"""
        self.__dict__.update(state)
        # 兜底：如果旧数据中缺失某些属性，在此处补全
        if not hasattr(self, '_context'):
            self._context = {}
        if not hasattr(self, 'items'):
            self.items = []

    @property
    def context(self) -> dict:
        if not hasattr(self, '_context') or self._context is None:
            self._context = {}
        return self._context

    @context.setter
    def context(self, value: dict):
        self._context = value or {}

    async def get_items(self, limit: Optional[int] = None) -> List[TResponseInputItem]:
        items = self.items if limit is None else self.items[-limit:]
        # 先收集交接调用的 call_id, 用于配对保留其输出条目
        handoff_call_ids = {
            _get_field(it, "call_id")
            for it in items
            if _is_handoff_call(it)
        }
        return [it for it in items if not _is_tool_history_item(it, handoff_call_ids)]

    async def add_items(self, items: List[TResponseInputItem]) -> None:
        self.items.extend(items)

    async def pop_item(self) -> Optional[TResponseInputItem]:
        if not self.items:
            return None
        return self.items.pop()

    async def clear_session(self) -> None:
        self.items = []
