import os
import sys

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infrastructure.ai.prompt_loader import load_prompt
from infrastructure.ai.openai_client import technical_model
from infrastructure.tools.local.knowledge_base import query_knowledge
from infrastructure.tools.local.web_search import builtin_web_search
from infrastructure.tools.mcp.mcp_servers import search_mac_client
from agents import Agent, ModelSettings, RunContextWrapper
from agents import Runner,RunConfig
from datetime import datetime


def _technical_instructions(agent: Agent, ctx: RunContextWrapper) -> str:
    """技术专家指令(动态): 静态提示词 + 每次运行时求值的系统时钟。
    模型自身无实时时钟, 不注入日期会把搜索结果中的旧日期(如2024年)误当"今日",
    或把未来活动预告当今日新闻(2026-09-05 线上故障)。callable 形式保证长期运行不陈旧。"""
    base = load_prompt("technical_agent")
    now = datetime.now()
    weekdays = "一二三四五六日"
    clock = (
        f"\n\n[系统时钟] 当前真实日期时间: {now.year}年{now.month}月{now.day}日 "
        f"星期{weekdays[now.weekday()]} {now.strftime('%H:%M')}。"
        f"回答任何时效性问题(新闻/天气/股价/新品/价格)必须以此日期为准:"
        f"搜索词中必须包含该年月日;结果只采信日期与当前接近的条目;"
        f"日期明显早于当前(如去年/前年)的是旧闻,晚于当前的是未来预告,均不得当作「今日」动态。"
    )
    return base + clock


# 1. 定义技术智能体
# 注意: MCP 注入后的联网搜索工具名同为 bailian_web_search（百炼侧命名），
# 因此本地兜底工具必须用不同名称 builtin_web_search，避免工具表重名冲突。
technical_agent = Agent(
    name="技术咨询专家",
    instructions=_technical_instructions,
    handoff_description="专门处理硬件故障诊断、软件问题排查、系统安装建议以及实时新闻/资讯查询（如天气、股价、最新技术发布等）。当用户询问“怎么做”、“为什么”、“是什么”或涉及实时数据时，请交接给此专家。",
    model=technical_model,
    model_settings=ModelSettings(temperature=0, extra_body={"tool_stream": True}),  # 流式工具调用必需（glm 系列需要；qwen 会忽略该参数）
    tools=[query_knowledge, builtin_web_search],
    # mcp_servers 将在运行时由调度者根据连接情况动态注入
)


# 2. 测试技术智能体
async def run_single_test(case_name: str, input_text: str):

    print(f"\n{'=' * 80}")
    print(f"测试用例: {case_name}")
    print(f"输入: \"{input_text}\"")
    print("-" * 80)
    try:
        # 尝试连接 MCP 服务，但即使失败也继续（Agent 会自动选择备选工具）
        try:
            await search_mac_client.connect()
            print("已连接到 MCP 搜索服务...")
        except Exception as e:
            print(f"警告: MCP 搜索服务连接失败 ({e})，将使用备选联网搜索工具。")
             
        print("思考中...")
        result = await Runner.run(technical_agent, input=input_text,run_config=RunConfig(tracing_disabled=True))
        print(f"\n\nAgent的最终输出: {result.final_output}")
    except Exception as e:
        import traceback
        print(f"\n Error: {e}")
        traceback.print_exc()
    finally:
        try:
            await search_mac_client.cleanup()
        except:
            pass


async def main():
    # 技术问题测试案例
    test_cases = [
        ("Case 1: 实时问题", "今天发生了哪些新鲜事"),
        ("Case 2: 技术问题", "电脑蓝屏了怎么办？"),
    ]

    for name, question in test_cases:
        await run_single_test(name, question)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

