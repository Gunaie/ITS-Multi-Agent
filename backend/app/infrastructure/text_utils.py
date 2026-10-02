"""文本处理工具: 从多种 LLM 响应对象中提取文本, 以及清洗运行时注入片段。"""
import re


def extract_text(obj, include_reasoning=False):
    """从字符串/列表/字典/OpenAI 风格对象中递归提取文本内容。

    include_reasoning=True 时会附带 reasoning_content 思考过程(用于前端展示)。
    """
    if not obj: return ""
    if isinstance(obj, str): return obj
    if isinstance(obj, list): return "".join([extract_text(i, include_reasoning) for i in obj])

    res = ""
    reasoning_attr = None
    content_attr = None

    # 1. 尝试获取 content 和 reasoning (处理 OpenAI 风格对象)
    content_attr = getattr(obj, "content", None)
    reasoning_attr = getattr(obj, "reasoning_content", None)

    # 2. 处理 ResponseOutputText / ResponseOutputMessage / ResponseOutputReasoningText 等新类型
    if not content_attr:
        content_attr = getattr(obj, "text", None)
    if not reasoning_attr:
        reasoning_attr = getattr(obj, "reasoning", None)

    # 3. 处理字典格式
    if isinstance(obj, dict):
        content_attr = content_attr or obj.get("content")
        reasoning_attr = reasoning_attr or obj.get("reasoning_content") or obj.get("reasoning")
        # 处理 choices 结构 (ChatCompletion 或 ChatCompletionChunk)
        if "choices" in obj and len(obj["choices"]) > 0:
            choice = obj["choices"][0]
            delta = choice.get("delta", {})
            message = choice.get("message", {})
            content_attr = content_attr or delta.get("content") or message.get("content")
            reasoning_attr = reasoning_attr or delta.get("reasoning_content") or message.get("reasoning_content")

    # 4. 处理 ChatCompletionChunk / ChatCompletion 对象
    if hasattr(obj, "choices") and len(obj.choices) > 0:
        choice = obj.choices[0]
        if hasattr(choice, "delta"):
            content_attr = content_attr or getattr(choice.delta, "content", None)
            reasoning_attr = reasoning_attr or getattr(choice.delta, "reasoning_content", None)
        elif hasattr(choice, "message"):
            content_attr = content_attr or getattr(choice.message, "content", None)
            reasoning_attr = reasoning_attr or getattr(choice.message, "reasoning_content", None)

    if include_reasoning and reasoning_attr:
        res += f"**[思考过程]**\n{reasoning_attr}\n\n---\n\n"

    if content_attr:
        if isinstance(content_attr, str):
            res += content_attr
        else:
            # 可能是列表或其他对象，递归提取
            res += extract_text(content_attr, include_reasoning)

    # 备选：text 属性 (兜底)
    if not res and not reasoning_attr:
        text = getattr(obj, "text", None) or (obj.get("text") if isinstance(obj, dict) else None)
        if text: res = str(text)

    return res


# 运行时注入片段的正则（这些片段随 Runner.run 的 input 自动写入会话历史，仅服务模型使用，
# 不应出现在前端展示/会话标题中）
_SYSTEM_CONTEXT_RE = re.compile(r"\s*\[系统上下文:[^\]]*\]")
_SYSTEM_DIRECTIVE_RE = re.compile(r"\[系统指令\][^\n]*\n?")


def clean_history_text(text: str) -> str:
    """剔除历史条目中的运行时注入片段（定位上下文尾部块 / 搜索意图指令头部行）。

    在 /sessions/{id} 读取侧清洗可同时覆盖新旧落库数据； compound 的 [系统提示]
    已在写入侧防双写删除, 此处不再处理。
    """
    if not text:
        return text
    cleaned = _SYSTEM_CONTEXT_RE.sub("", text)
    cleaned = _SYSTEM_DIRECTIVE_RE.sub("", cleaned)
    return cleaned.strip()
