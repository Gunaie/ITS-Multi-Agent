import os
import sys
import asyncio

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from multi_agent.orchestrator import orchestrator_agent
from agents import Runner, RunConfig

import io
import sys

# 解决 Windows 终端编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

async def main():
    query = "开机之后没有任何反应怎么解决，如果解决不了，我准备去附近的维修站维修"
    print(f"\n测试意图: {query}")
    print("-" * 50)
    
    try:
        # 运行编排智能体
        result = await Runner.run(
            orchestrator_agent, 
            input=query,
            run_config=RunConfig(tracing_disabled=True)
        )
        # 安全打印输出
        output = result.final_output
        print("\n最终输出:")
        print(output.encode('utf-8', errors='replace').decode('utf-8'))
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
