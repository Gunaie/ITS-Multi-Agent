"""
会话历史摘要压缩 - 单元测试（无外部服务依赖，mock LLM）

覆盖: 阈值不触发 / 触发压缩 / 信息保留 / LLM失败兜底 / 重复压缩

运行:
    python backend/tests/test_history_compression.py
"""
import os
import sys
import asyncio
from unittest.mock import AsyncMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _APP_DIR)
sys.path.insert(0, _BACKEND_DIR)

PASS = 0
FAIL = 0

def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def make_items(n: int) -> list:
    """生成 n 轮对话（2n 条 items）。"""
    items = []
    for i in range(n):
        items.append({"role": "user", "content": f"用户问题{i}"})
        items.append({"role": "assistant", "content": f"助手回答{i}"})
    return items


from infrastructure.database.session_impl import SimpleSession
from infrastructure.ai import history_compression

# ---------------------------------------------------------------------------

print("\n[1] 阈值不触发：items ≤ 24 → 不压缩")

async def test_no_compression():
    session = SimpleSession(session_id="test1")
    session.items = make_items(5)  # 10 条 < 24
    orig = len(session.items)
    await history_compression.compress_history_if_needed(session)
    check("条目数不变", len(session.items) == orig, f"expected {orig}, got {len(session.items)}")
    check("无摘要条目", not any("[对话历史摘要]" in str(it.get("content", "")) for it in session.items))

asyncio.run(test_no_compression())

# ---------------------------------------------------------------------------

print("\n[2] 触发压缩：30 条 → 压缩后 ≤ 11 条，首条含摘要标记")

async def test_triggers_compression():
    session = SimpleSession(session_id="test2")
    session.items = make_items(15)  # 30 条 > 24
    with patch.object(history_compression, "_llm_summarize", new_callable=AsyncMock, return_value="这是测试摘要"):
        await history_compression.compress_history_if_needed(session)
    check("压缩后条目数 = KEEP_RECENT+1", len(session.items) == 11, f"got {len(session.items)}")
    check("首条含[对话历史摘要]", "[对话历史摘要]" in session.items[0].get("content", ""), session.items[0].get("content", "")[:50])
    check("摘要内容在首条", "这是测试摘要" in session.items[0].get("content", ""))
    check("末尾保留近期条目", session.items[-1].get("content") == "助手回答14")

asyncio.run(test_triggers_compression())

# ---------------------------------------------------------------------------

print("\n[3] 信息保留：摘要输入文本含原始关键词")

async def test_info_preserved():
    session = SimpleSession(session_id="test3")
    items = make_items(15)
    # 在旧条目中插入特定关键词
    items[0] = {"role": "user", "content": "我的联想笔记本黑屏了"}
    items[1] = {"role": "assistant", "content": "建议重装显卡驱动，请问你在武汉吗？"}
    session.items = items
    captured = {}
    async def fake_summarize(text_block):
        captured["text"] = text_block
        return "用户笔记本黑屏，建议重装显卡驱动，用户在武汉"
    with patch.object(history_compression, "_llm_summarize", side_effect=fake_summarize):
        await history_compression.compress_history_if_needed(session)
    text = captured.get("text", "")
    check("摘要输入含'黑屏'", "黑屏" in text)
    check("摘要输入含'显卡驱动'", "显卡驱动" in text)
    check("摘要输入含'武汉'", "武汉" in text)
    check("摘要输入含'用户:'标签", "用户:" in text)
    check("摘要输入含'助手:'标签", "助手:" in text)

asyncio.run(test_info_preserved())

# ---------------------------------------------------------------------------

print("\n[4] LLM 失败兜底：_llm_summarize 返回空 → 截断标记 + 保留近期")

async def test_llm_failure_fallback():
    session = SimpleSession(session_id="test4")
    session.items = make_items(15)  # 30 条
    with patch.object(history_compression, "_llm_summarize", new_callable=AsyncMock, return_value=""):
        await history_compression.compress_history_if_needed(session)
    check("兜底后条目数 = 11", len(session.items) == 11, f"got {len(session.items)}")
    check("首条含截断标记", "截断" in session.items[0].get("content", ""), session.items[0].get("content", "")[:50])
    check("末尾保留近期", session.items[-1].get("content") == "助手回答14")

asyncio.run(test_llm_failure_fallback())

# ---------------------------------------------------------------------------

print("\n[5] 重复压缩：压缩后再加条目 → 再次压缩，摘要输入含旧摘要")

async def test_repeated_compression():
    session = SimpleSession(session_id="test5")
    session.items = make_items(15)  # 30 条
    with patch.object(history_compression, "_llm_summarize", new_callable=AsyncMock, return_value="第一次摘要"):
        await history_compression.compress_history_if_needed(session)
    check("第一次压缩后 11 条", len(session.items) == 11, f"got {len(session.items)}")

    # 再加 20 条 → 31 条，再次超阈值
    session.items.extend(make_items(10))
    check("扩展后 31 条", len(session.items) == 31, f"got {len(session.items)}")

    captured = {}
    async def fake_summarize2(text_block):
        captured["text"] = text_block
        return "整合后的摘要"
    with patch.object(history_compression, "_llm_summarize", side_effect=fake_summarize2):
        await history_compression.compress_history_if_needed(session)
    text = captured.get("text", "")
    check("第二次摘要输入含旧摘要", "第一次摘要" in text or "对话历史摘要" in text, f"text starts: {text[:80]}")
    check("第二次压缩后 11 条", len(session.items) == 11, f"got {len(session.items)}")
    check("首条含整合后的摘要", "整合后的摘要" in session.items[0].get("content", ""))

asyncio.run(test_repeated_compression())

# ---------------------------------------------------------------------------

print(f"\n{'='*50}")
print(f"结果: {PASS} 通过, {FAIL} 失败")
sys.exit(0 if FAIL == 0 else 1)
