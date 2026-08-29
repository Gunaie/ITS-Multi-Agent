from typing import List
import logging
import os
import re
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from config.settings import settings

from common.infrastructure.logging.logger import logger

class QueryService:
    """检索服务"""

    def __init__(self):

        self.llm=ChatOpenAI(model_name=settings.MODEL,
                            openai_api_key=settings.API_KEY,
                            openai_api_base=settings.BASE_URL,
                            temperature=0,
                            timeout=60) # temperature作用：控制模型输出的随机度



    def generate_answer(self, user_question:str, retrival_context: List[Document]) -> str:
        """
        对接大语言模型的入口
        Args:
            user_question: 用户问题
            retrival_context: 检索到的上下文

        Returns:
            str:LLM模型整合上下文之后的自然语言
        """

        # 1. 判断是否检索到了文档
        if not  retrival_context:
            # 即使没检索到，也应保持身份认知
            prompt = f"""
            你是由 ITS 多智能体系统驱动的“ITS 智能技术支持助手”。
            对于用户的问题：“{user_question}”，当前的知识库中暂时没有找到相关的解决方案。
            请礼貌地告知用户，并根据你的通用知识尝试给出建议，但需说明这些建议并非来自官方知识库。
            """
            llm_response=self.llm.invoke(prompt)
            return llm_response.content


        # 2. 处理检索到的知识内容
        formatted_context = []
        for index, doc in enumerate(retrival_context):
            file_path = doc.metadata.get('path', '未知文件')
            file_name = os.path.basename(file_path)
            # 更安全的清理内容中的“文档来源:”标记
            content = doc.page_content
            if content.startswith("文档来源:"):
                parts = content.split("\n", 1)
                clean_content = parts[1].strip() if len(parts) > 1 else ""
            else:
                clean_content = content.strip()
            
            formatted_context.append(f"【文件{index+1}：{file_name}】\n内容：{clean_content}")
        
        context_str = "\n\n".join(formatted_context)

        # 3. 定义提示词
        prompt = f"""
        你是由 ITS 多智能体系统驱动的“ITS 智能技术支持助手”，是一位经验丰富的高级技术支持专家。
        请基于下方的【参考资料】回答【用户问题】。

         【参考资料】：
         ```
         {context_str}
         ```

         【用户问题】：
         ```
         {user_question}
         ```

         【回答要求】：
         1.  **身份认知**：你是“ITS 智能技术支持助手”。如果用户问你是谁，请明确告知。
         2.  **基于事实**：严格基于【参考资料】的内容回答，严禁编造资料中未提及的信息。如果资料无法回答问题，请直接回答：“当前的知识库中暂时没有找到该问题的解决方案。”
         3.  **标注来源**：(极其重要)
             - 在回答每一个具体知识点或步骤时，必须在其后紧跟引用来源的文件名。
             - 格式为：`[文件名]`。
             - 例如：“第一步：检查电源连接 [电源故障排查指南.md]。第二步：长按开机键 [常见问题汇总.md]。”
             - 严禁使用“资料1”、“来源1”等模糊表述，必须使用【参考资料】中明确给出的真实文件名。
         4.  **去特定化处理**：
             - 除非用户问题中明确指明了特定型号/品牌，否则在回答中请移除具体的设备型号、品牌名称。
         5.  **结构清晰**：
             - 使用 Markdown 格式。如果是操作步骤，请使用有序列表（1. 2. 3.）。

         【开始回答】：
         """

        # 4. 调用模型
        try:
            llm_response=self.llm.invoke(prompt)
            # 5. 返回模型的结果
            return  llm_response.content
        except Exception as e:
            logger.error(f"LLM 生成回答失败: {e}")
            return "抱歉，我在生成回答时遇到了问题。但我可以告诉你，根据检索到的资料，这可能与电源或静电有关。请检查电源线连接或尝试释放静电。"

    def rerank_documents(self, user_question: str, documents: List[Document]) -> List[Document]:
        """
        使用 LLM 对检索到的文档进行重排序 (Rerank)
        """
        if not documents:
            return []
            
        doc_list = "\n".join([f"ID {i}: {doc.page_content[:500]}..." for i, doc in enumerate(documents)])
        
        prompt = f"""
        作为一名搜索排序专家，请根据用户问题与文档的相关性，对以下文档进行打分（0-10分）。
        只需返回最相关的 ID 列表，按相关性从高到低排列，格式为：[ID1, ID2, ...]
        
        【用户问题】：{user_question}
        
        【待排序文档】：
        {doc_list}
        
        【结果】：
        """
        
        try:
            response = self.llm.invoke(prompt)
            # 使用更宽容的正则提取 ID
            ids_str = re.findall(r'ID\s*[:：]?\s*(\d+)|\b(\d+)\b', response.content)
            # 展平匹配结果并转换为整数
            ids = []
            for match in ids_str:
                id_val = match[0] or match[1]
                if id_val:
                    ids.append(int(id_val))
            
            reranked_docs = []
            seen_indices = set()
            
            for idx in ids:
                if idx < len(documents) and idx not in seen_indices:
                    reranked_docs.append(documents[idx])
                    seen_indices.add(idx)
            
            # 补齐未出现在列表中的文档 (平稳退化)
            for i, doc in enumerate(documents):
                if i not in seen_indices:
                    reranked_docs.append(doc)
            
            return reranked_docs
        except Exception as e:
            logger.warning(f"Rerank parsing failed or LLM error: {e}. Falling back to original order.")
            return documents





