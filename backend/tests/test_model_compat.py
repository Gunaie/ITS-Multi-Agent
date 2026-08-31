"""
模型可用性验证脚本（阶段1）

实测三个目标模型在百炼 OpenAI 兼容端点下的可用性：
1. qwen3.7-max-2026-06-08（orchestrator 候选）—— 基本 chat
2. glm-5.2（technical 候选）—— 工具调用，验证 tool_stream 透传
3. deepseek-v4-flash-0731（service 候选）—— 工具调用

运行：
    cd backend/tests
    python test_model_compat.py
"""
import os
import sys
import asyncio

# 把 backend/app 和 backend 加入路径，以便 import config.settings
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "app")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))

from openai import AsyncOpenAI
from config.settings import settings

# 简单工具定义：get_weather，用于验证模型 tool_calls 返回
WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的天气",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"}
            },
            "required": ["city"],
        },
    },
}


def make_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.AL_BAILIAN_BASE_URL,
        api_key=settings.AL_BAILIAN_API_KEY,
    )


async def test_basic_chat(client: AsyncOpenAI, model: str) -> tuple[bool, str]:
    """基本对话测试，返回 (是否成功, 摘要信息)"""
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是联想售后客服助手，回答简洁。"},
                {"role": "user", "content": "你是谁？一句话回答。"},
            ],
            temperature=0,
            max_tokens=100,
        )
        content = resp.choices[0].message.content or "(空)"
        return True, content.strip()[:80]
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def test_tool_call(
    client: AsyncOpenAI,
    model: str,
    extra_body: dict | None = None,
) -> tuple[bool, str]:
    """工具调用测试，验证模型能否返回 tool_calls"""
    try:
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是联想售后客服助手，需要时调用工具查询信息。"},
                {"role": "user", "content": "北京今天天气怎么样？请用工具查询。"},
            ],
            "tools": [WEATHER_TOOL],
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 200,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        resp = await client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            tc = tool_calls[0]
            return True, f"tool_calls: name={tc.function.name}, args={tc.function.arguments}"
        content = (msg.content or "(空)").strip()[:80]
        return False, f"未返回 tool_calls，直接回答: {content}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def main():
    print("=" * 70)
    print("模型可用性验证（百炼 OpenAI 兼容端点）")
    print(f"base_url: {settings.AL_BAILIAN_BASE_URL}")
    print("=" * 70)

    client = make_client()

    # 1. qwen3.7-max-2026-06-08 基本 chat
    print("\n[1/3] qwen3.7-max-2026-06-08 基本 chat")
    ok, info = await test_basic_chat(client, "qwen3.7-max-2026-06-08")
    print(f"  结果: {'✅ 成功' if ok else '❌ 失败'} | {info}")

    # 2. glm-5.2 工具调用（带 tool_stream）
    print("\n[2/3] glm-5.2 工具调用（extra_body tool_stream=True）")
    ok, info = await test_tool_call(
        client, "glm-5.2", extra_body={"tool_stream": True}
    )
    print(f"  结果: {'✅ 成功' if ok else '❌ 失败'} | {info}")

    # 2b. glm-5.2 工具调用（不带 tool_stream，对照）
    print("\n[2b] glm-5.2 工具调用（不带 tool_stream，对照）")
    ok, info = await test_tool_call(client, "glm-5.2")
    print(f"  结果: {'✅ 成功' if ok else '❌ 失败'} | {info}")

    # 3. deepseek-v4-flash-0731 工具调用
    print("\n[3/3] deepseek-v4-flash-0731 工具调用")
    ok, info = await test_tool_call(client, "deepseek-v4-flash-0731")
    print(f"  结果: {'✅ 成功' if ok else '❌ 失败'} | {info}")

    print("\n" + "=" * 70)
    print("验证完成")
    print("=" * 70)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
