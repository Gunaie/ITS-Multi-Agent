import os
import sys

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import set_tracing_disabled

set_tracing_disabled(True)
from agents import Agent, ModelSettings, RunContextWrapper
from infrastructure.ai.openai_client import service_model
from infrastructure.tools.local.service_station import (
    get_nearby_official_repair_stations,
    map_uri
)
# 移除冗余的子工具导入，仅保留高速集成工具
# resolve_user_location_from_text 也不再直接暴露给 Agent，由集成工具内部调用

from infrastructure.ai.prompt_loader import load_prompt

# 基础提示词（静态部分）
_BASE_SERVICE_PROMPT = load_prompt("comprehensive_service_agent")


async def _service_instructions(ctx: RunContextWrapper, agent: Agent) -> str:
    """动态指令：将会话中已捕获的定位线索注入系统提示词末尾。

    背景: temperature=0 下, 若历史中存在"追问城市"的助手回复, 模型在收到用户补充地点后
    容易复读追问文案而不调用工具。系统提示词末尾的确定性指令能有效压过这种历史模仿。
    """
    prompt = _BASE_SERVICE_PROMPT
    try:
        session = getattr(ctx, "context", None)
        ctx_dict = {}
        if session is not None:
            raw = getattr(session, "context", None)
            if isinstance(raw, dict):
                ctx_dict = raw
        pending = str(ctx_dict.get("location_hint_pending") or "").strip()
        record = ctx_dict.get("location_record") if isinstance(ctx_dict.get("location_record"), dict) else {}
        coords = str(record.get("coords") or "").strip()
        if pending:
            prompt += (
                "\n\n## ⚡ 系统上下文注入（本轮最高优先级，覆盖历史对话）\n"
                f"系统已从会话中捕获到用户提供的地点：「{pending}」。\n"
                "你必须**立即调用** get_nearby_official_repair_stations，"
                f"并将参数 location_hint 填为 \"{pending}\"。\n"
                "**严禁**再次追问城市，**严禁**重复历史中的任何追问文案——用户已经提供地点了。"
            )
        elif coords:
            prompt += (
                "\n\n## ⚡ 系统上下文注入（本轮最高优先级，覆盖历史对话）\n"
                f"系统已持有用户定位坐标（{coords}）。\n"
                "你必须**立即调用** get_nearby_official_repair_stations（location_hint 传空字符串）。\n"
                "**严禁**追问城市。"
            )
    except Exception:
        # 注入失败不影响基础提示词
        pass
    return prompt

# 16. 定义服务智能体
comprehensive_service_agent = Agent(
    name="业务服务专家",
    instructions=_service_instructions,
    handoff_description="专门处理维修站查询、地理位置定位、周边服务点搜索以及地图导航指引。当用户询问“哪里有”、“怎么去”或涉及地点、服务网网点时，请交接给此专家。",
    model=service_model,
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
