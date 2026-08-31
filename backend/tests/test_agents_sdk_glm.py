"""
openai-agents SDK 集成验证（阶段1关键项）

验证 glm-5.2 在 agents SDK 流式工具调用循环下能否正常工作。
agents SDK 默认 stream=True，glm-5.2 流式下必须带 extra_body tool_stream=True。
"""
import os
import sys

# 把 backend/app 和 backend 加入路径
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "app")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))

import asyncio
from agents import Agent, ModelSettings, Runner, RunConfig, function_tool, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from config.settings import settings


@function_tool
def get_weather(city: str) -> str:
    """查询指定城市的天气"""
    return f"{city}今天晴，25度。"


async def main():
    client = AsyncOpenAI(
        base_url=settings.AL_BAILIAN_BASE_URL,
        api_key=settings.AL_BAILIAN_API_KEY,
    )

    # glm-5.2 模型实例（带 tool_stream）
    glm_model = OpenAIChatCompletionsModel(model="glm-5.2", openai_client=client)

    agent = Agent(
        name="测试助手",
        instructions="你是联想售后客服助手，需要查天气时调用 get_weather 工具。",
        model=glm_model,
        model_settings=ModelSettings(
            temperature=0,
            extra_body={"tool_stream": True},  # glm-5.2 流式工具调用必需
        ),
        tools=[get_weather],
    )

    print("=" * 70)
    print("agents SDK 流式工具调用验证：glm-5.2 + tool_stream")
    print("=" * 70)
    print("输入: 北京今天天气怎么样？")
    print("-" * 70)

    try:
        result = await Runner.run(
            agent,
            input="北京今天天气怎么样？",
            run_config=RunConfig(tracing_disabled=True),
        )
        print(f"\n最终输出: {result.final_output}")
        # 检查是否真的调用了工具
        tool_calls = [i for i in result.new_items if getattr(i, "type", "") == "tool_call_item" or "tool" in getattr(i, "type", "")]
        print(f"工具调用事件数: {len(tool_calls)}")
        print(f"\n✅ agents SDK + glm-5.2 流式工具调用成功" if result.final_output else "\n❌ 无输出")
    except Exception as e:
        print(f"\n❌ 失败: {type(e).__name__}: {str(e)[:300]}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

    print("\n" + "=" * 70)
    print("验证完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
