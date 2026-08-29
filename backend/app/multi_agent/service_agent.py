import os
import sys

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import set_tracing_disabled

set_tracing_disabled(True)
from agents import Agent, ModelSettings
from infrastructure.ai.openai_client import sub_model
from infrastructure.tools.local.service_station import (
    get_nearby_official_repair_stations,
    map_uri
)
# 移除冗余的子工具导入，仅保留高速集成工具
# resolve_user_location_from_text 也不再直接暴露给 Agent，由集成工具内部调用

from infrastructure.ai.prompt_loader import load_prompt

# 16. 定义服务智能体
comprehensive_service_agent = Agent(
    name="业务服务专家",
    instructions=load_prompt("comprehensive_service_agent"),
    handoff_description="专门处理维修站查询、地理位置定位、周边服务点搜索以及地图导航指引。当用户询问“哪里有”、“怎么去”或涉及地点、服务网网点时，请交接给此专家。",
    model=sub_model,
    model_settings=ModelSettings(
        temperature=0,
        max_tokens=2048,
    ),
    # 仅保留高速集成工具和导航工具，彻底杜绝模型链式调用
    tools=[
        get_nearby_official_repair_stations,
        map_uri
    ],
    # mcp_servers 将在运行时由调度者根据连接情况动态注入
)


async def run_single_test(case_name: str, input_text: str):
    from agents import Runner

    """运行单个测试并打印详细信息"""
    print(f"\n{'=' * 80}")
    print(f"测试用例: {case_name}")
    print(f"输入: \"{input_text}\"")
    print("-" * 80)
    try:
        # 百度地图 API 已集成在集成工具内部，无需手动连接 MCP
        print("⏳ 思考中...")
        # result = await Runner.run(comprehensive_service_agent, input=input_text)

        # 使用流式处理
        result = Runner.run_streamed(
            starting_agent=comprehensive_service_agent,
            input=input_text,
        )

        # 打印关键事件
        async for event in result.stream_events():
            # 工具调用事件
            if event.type == "run_item_stream_event":
                if hasattr(event, "name") and event.name == "tool_called":
                    from agents import ToolCallItem
                    if isinstance(event.item, ToolCallItem):
                        raw_item = event.item.raw_item
                        print(f"\n调用工具名:{raw_item.name}--->工具参数:{raw_item.arguments}")
                elif hasattr(event, 'name') and event.name == "tool_output":
                    from agents import ToolCallOutputItem
                    if isinstance(event.item, ToolCallOutputItem):
                        print(f"调用工具结果:{event.item.output}")

        print(f"\n\nAgent的最终输出: {result.final_output}")
    except Exception as e:
        print(f"\n Error: {e}\n")
    finally:
        pass


async def main():
    # 服务站和地图测试案例
    test_cases = [
         ("Case 1: 服务站查询", "查一下最近的维修站"),
    ]

    for name, question in test_cases:
        await run_single_test(name, question)



if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
