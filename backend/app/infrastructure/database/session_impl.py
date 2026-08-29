from agents.memory import SessionABC
from agents.items import TResponseInputItem
from typing import List, Optional

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
        if limit is None:
            return self.items
        return self.items[-limit:]

    async def add_items(self, items: List[TResponseInputItem]) -> None:
        self.items.extend(items)

    async def pop_item(self) -> Optional[TResponseInputItem]:
        if not self.items:
            return None
        return self.items.pop()

    async def clear_session(self) -> None:
        self.items = []
