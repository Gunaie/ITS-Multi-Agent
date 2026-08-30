import os
import sys
import asyncio
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevance,
    context_precision,
    context_recall,
)
from langchain_openai import ChatOpenAI

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "app"))

from config.settings import settings
from infrastructure.tools.local.knowledge_base import query_knowledge

# 评估数据集
EVAL_DATA = [
    {
        "question": "电脑开机之后没有任何反应怎么解决？",
        "ground_truth": "检查电源线（主机接口和插线板）是否正常连接。断开电源线，多按几次电源开关，消除静电屏蔽，释放静电，连接电源线，开机重试。"
    },
    {
        "question": "昭阳K43机型只使用电池找不到网络设备怎么办？",
        "ground_truth": "这通常是由于电源管理设置导致的。建议检查电池模式下的无线网卡供电设置，或者更新最新的电源管理驱动。"
    },
    {
        "question": "如何修改 Microsoft Word 的默认样式？",
        "ground_truth": "在‘开始’选项卡上，右键单击‘样式’库中的‘正文’样式，然后选择‘修改’。选择所需的格式，然后选择‘基于该模板的新文档’。"
    }
]

async def run_evaluation():
    print("开始 Ragas 自动化评估...")
    
    questions = [d["question"] for d in EVAL_DATA]
    ground_truths = [[d["ground_truth"]] for d in EVAL_DATA]
    answers = []
    contexts = []

    # 1. 获取模型回答和上下文
    for q in questions:
        print(f"正在测试问题: {q}")
        # 这里假设 query_knowledge 返回的是带引用信息的字符串
        # 实际项目中可能需要从工具返回的原始数据中提取 context
        # 为了演示，我们直接使用工具返回的内容作为 answer，并尝试模拟 context 提取
        try:
            # query_knowledge 是一个被 pydantic-ai 包装的工具
            if hasattr(query_knowledge, "__wrapped__"):
                res = await query_knowledge.__wrapped__(q)
            else:
                res = await query_knowledge(q)
            
            answers.append(res)
            # 简单模拟提取上下文（实际应从检索器获取）
            contexts.append([res]) 
        except Exception as e:
            print(f"查询失败: {e}")
            answers.append("Error")
            contexts.append(["Error"])

    # 2. 准备数据集
    data = {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths
    }
    dataset = Dataset.from_dict(data)

    # 3. 初始化评估模型 (使用百炼接口)
    llm = ChatOpenAI(
        model=settings.MAIN_MODEL_NAME,
        openai_api_key=settings.AL_BAILIAN_API_KEY,
        openai_api_base=settings.AL_BAILIAN_BASE_URL,
    )

    # 4. 执行评估
    print("正在计算 Ragas 指标...")
    result = evaluate(
        dataset,
        metrics=[
            faithfulness,
            answer_relevance,
            context_precision,
            context_recall,
        ],
        llm=llm
    )

    print("\n评估结果:")
    print(result)
    
    # 保存结果
    import pandas as pd
    df = result.to_pandas()
    output_path = os.path.join(os.path.dirname(__file__), "eval_results.csv")
    df.to_csv(output_path, index=False)
    print(f"详细结果已保存至: {output_path}")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
