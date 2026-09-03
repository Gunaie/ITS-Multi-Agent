"""会话历史摘要压缩模块。

多轮对话历史超阈值时，用 glm-5.2 将旧条目摘要为单条消息，
保留最近几轮原文，防止 LLM 上下文窗口溢出与成本上升。
"""
import asyncio
import logging

from config.settings import settings
from infrastructure.ai.openai_client import _model_client, TECHNICAL_MODEL_NAME

logger = logging.getLogger(__name__)

# 工具调用类条目类型——摘要时跳过（与 session_impl._TOOL_HISTORY_TYPES 保持一致）
_TOOL_TYPES = {
    "function_call",
    "function_call_output",
    "tool_call",
    "tool_call_output",
    "hosted_tool_call",
    "hosted_tool_call_output",
    "web_search_call",
    "reasoning",
}

_SUMMARY_SYSTEM_PROMPT = (
    "你是对话摘要助手。将以下联想售后客服对话历史压缩为简洁摘要（≤300字），必须保留：\n"
    "1. 用户的核心问题/设备型号/症状\n"
    "2. 已给出的诊断或建议\n"
    "3. 用户提到的城市/地点（如有）\n"
    "4. 尚未解决的问题\n"
    "若输入已含「[对话历史摘要]」，将其与新内容整合为一份摘要。"
    "直接输出摘要正文，不要加多余前缀。"
)


def _get_field(item, key):
    """兼容 dict / object 两种条目形态取字段。"""
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _build_summary_input(items) -> str:
    """从历史条目提取对话文本（过滤工具调用/推理过程）。

    保留 user / assistant 的文本内容，跳过 function_call 等工具类条目，
    输出 "用户: ... / 助手: ..." 格式供 LLM 摘要。
    """
    lines = []
    for item in items:
        item_type = _get_field(item, "type")
        if item_type in _TOOL_TYPES:
            continue
        role = _get_field(item, "role") or ""
        content = _get_field(item, "content")
        if content is None:
            continue
        # content 可能是 str / list[dict] / 其他
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict):
                    parts.append(p.get("text", ""))
                elif isinstance(p, str):
                    parts.append(p)
            content = " ".join(parts)
        content = str(content).strip()
        if not content:
            continue
        label = "用户" if role == "user" else "助手" if role == "assistant" else role
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


async def _llm_summarize(text_block: str) -> str:
    """调 glm-5.2 对话历史文本生成摘要。失败时返回空串，由调用方走兜底。"""
    if not text_block.strip():
        return ""
    try:
        resp = await asyncio.wait_for(
            _model_client.chat.completions.create(
                model=TECHNICAL_MODEL_NAME,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": text_block},
                ],
                temperature=0,
                max_tokens=512,
            ),
            timeout=20,
        )
        summary = (resp.choices[0].message.content or "").strip()
        logger.info(f"History compressed: {len(text_block)} chars -> {len(summary)} chars summary")
        return summary
    except Exception as e:
        logger.warning(f"History summary LLM call failed, fallback to truncation: {e}")
        return ""


async def compress_history_if_needed(session) -> None:
    """超阈值时压缩会话历史：旧条目 LLM 摘要 + 保留最近 KEEP_RECENT 条。

    在 Runner.run 前调用。阈值由 settings.SESSION_COMPRESS_THRESHOLD 控制。
    LLM 失败时退化为截断标记，不抛异常。
    """
    items = getattr(session, "items", None)
    if not items:
        return

    threshold = settings.SESSION_COMPRESS_THRESHOLD
    keep = settings.SESSION_COMPRESS_KEEP_RECENT

    if len(items) <= threshold:
        return

    old_items = items[:-keep]
    recent = items[-keep:]

    text_block = _build_summary_input(old_items)
    summary = await _llm_summarize(text_block)

    if not summary:
        # 兜底：LLM 失败，截断并标记
        summary = f"历史过长，已截断前 {len(old_items)} 条记录"

    session.items = [
        {"role": "user", "content": f"[对话历史摘要]\n{summary}"}
    ] + list(recent)
    logger.info(
        f"Session history compressed: {len(old_items) + len(recent)} -> {len(session.items)} items"
    )
