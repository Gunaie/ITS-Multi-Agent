# RAG 评估体系

本目录包含基于 **Ragas** 框架的自动化评估脚本，用于量化联想售后知识库的检索与生成质量。

## 核心指标
- **Faithfulness (忠实度)**: 回答是否严格基于检索到的上下文，无幻觉。
- **Answer Relevance (回答相关性)**: 回答是否直接且准确地解决了用户问题。
- **Context Precision (上下文精度)**: 检索到的文档片段是否包含正确答案。
- **Context Recall (上下文召回率)**: 检索到的文档是否覆盖了 Ground Truth 中的关键点。

## 使用方法
1. 确保已安装依赖：
   ```bash
   uv pip install ragas datasets langchain-openai
   ```
2. 配置 `.env` 文件中的 `AL_BAILIAN_API_KEY`。
3. 运行评估脚本：
   ```bash
   python tests/evaluation/rag_eval.py
   ```

## 输出结果
评估完成后，将生成 `eval_results.csv` 文件，包含每个测试用例的详细得分，便于进行回归测试和基准分析。
