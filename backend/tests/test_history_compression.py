"""
会话历史摘要压缩 - 单元测试（无外部服务依赖，mock LLM）

覆盖: 阈值不触发 / 触发压缩 / 信息保留 / LLM失败兜底 / 重复压缩

运行:
    pytest backend/tests/test_history_compression.py -v
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, patch

# 兼容直接以脚本方式运行
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _APP_DIR)
sys.path.insert(0, _BACKEND_DIR)

from infrastructure.database.session_impl import SimpleSession
from infrastructure.ai import history_compression


def make_items(n: int) -> list:
    """生成 n 轮对话（2n 条 items）。"""
    items = []
    for i in range(n):
        items.append({"role": "user", "content": f"用户问题{i}"})
        items.append({"role": "assistant", "content": f"助手回答{i}"})
    return items


# ---------------------------------------------------------------------------
# [1] 阈值不触发：items ≤ 24 → 不压缩
# ---------------------------------------------------------------------------
def test_no_compression():
    async def scenario():
        session = SimpleSession(session_id="test1")
        session.items = make_items(5)  # 10 条 < 24
        orig = len(session.items)
        await history_compression.compress_history_if_needed(session)
        return session, orig

    session, orig = asyncio.run(scenario())
    assert len(session.items) == orig                              # 条目数不变
    assert not any("[对话历史摘要]" in str(it.get("content", "")) for it in session.items)  # 无摘要条目


# ---------------------------------------------------------------------------
# [2] 触发压缩：30 条 → 压缩后 11 条，首条含摘要标记
# ---------------------------------------------------------------------------
def test_triggers_compression():
    async def scenario():
        session = SimpleSession(session_id="test2")
        session.items = make_items(15)  # 30 条 > 24
        with patch.object(history_compression, "_llm_summarize",
                          new_callable=AsyncMock, return_value="这是测试摘要"):
            await history_compression.compress_history_if_needed(session)
        return session

    session = asyncio.run(scenario())
    assert len(session.items) == 11                               # 压缩后条目数 = KEEP_RECENT+1
    assert "[对话历史摘要]" in session.items[0].get("content", "")  # 首条含[对话历史摘要]
    assert "这是测试摘要" in session.items[0].get("content", "")     # 摘要内容在首条
    assert session.items[-1].get("content") == "助手回答14"          # 末尾保留近期条目


# ---------------------------------------------------------------------------
# [3] 信息保留：摘要输入文本含原始关键词
# ---------------------------------------------------------------------------
def test_info_preserved():
    async def scenario():
        session = SimpleSession(session_id="test3")
        items = make_items(15)
        items[0] = {"role": "user", "content": "我的联想笔记本黑屏了"}
        items[1] = {"role": "assistant", "content": "建议重装显卡驱动，请问你在武汉吗？"}
        session.items = items
        captured = {}

        async def fake_summarize(text_block):
            captured["text"] = text_block
            return "用户笔记本黑屏，建议重装显卡驱动，用户在武汉"

        with patch.object(history_compression, "_llm_summarize", side_effect=fake_summarize):
            await history_compression.compress_history_if_needed(session)
        return captured

    text = asyncio.run(scenario()).get("text", "")
    assert "黑屏" in text           # 摘要输入含'黑屏'
    assert "显卡驱动" in text       # 摘要输入含'显卡驱动'
    assert "武汉" in text           # 摘要输入含'武汉'
    assert "用户:" in text          # 摘要输入含'用户:'标签
    assert "助手:" in text          # 摘要输入含'助手:'标签


# ---------------------------------------------------------------------------
# [4] LLM 失败兜底：_llm_summarize 返回空 → 截断标记 + 保留近期
# ---------------------------------------------------------------------------
def test_llm_failure_fallback():
    async def scenario():
        session = SimpleSession(session_id="test4")
        session.items = make_items(15)  # 30 条
        with patch.object(history_compression, "_llm_summarize",
                          new_callable=AsyncMock, return_value=""):
            await history_compression.compress_history_if_needed(session)
        return session

    session = asyncio.run(scenario())
    assert len(session.items) == 11                               # 兜底后条目数 = 11
    assert "截断" in session.items[0].get("content", "")           # 首条含截断标记
    assert session.items[-1].get("content") == "助手回答14"          # 末尾保留近期


# ---------------------------------------------------------------------------
# [5] 重复压缩：压缩后再加条目 → 再次压缩，摘要输入含旧摘要
# ---------------------------------------------------------------------------
def test_repeated_compression():
    async def scenario():
        session = SimpleSession(session_id="test5")
        session.items = make_items(15)  # 30 条
        with patch.object(history_compression, "_llm_summarize",
                          new_callable=AsyncMock, return_value="第一次摘要"):
            await history_compression.compress_history_if_needed(session)

        # 再加 20 条 → 31 条，再次超阈值
        session.items.extend(make_items(10))

        captured = {}

        async def fake_summarize2(text_block):
            captured["text"] = text_block
            return "整合后的摘要"

        with patch.object(history_compression, "_llm_summarize", side_effect=fake_summarize2):
            await history_compression.compress_history_if_needed(session)
        return session, captured

    session, captured = asyncio.run(scenario())
    text = captured.get("text", "")
    assert "第一次摘要" in text or "对话历史摘要" in text           # 第二次摘要输入含旧摘要
    assert len(session.items) == 11                               # 第二次压缩后 11 条
    assert "整合后的摘要" in session.items[0].get("content", "")      # 首条含整合后的摘要
