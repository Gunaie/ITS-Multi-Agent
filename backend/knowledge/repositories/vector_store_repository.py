# 1. 优先import

import logging
logger=logging.getLogger(__name__)


# 2. from三方的
from langchain_community.vectorstores import Chroma
from config.settings import settings
from langchain_core.documents import Document
from langchain_openai.embeddings import OpenAIEmbeddings
from typing import List

# 3. from 自己的
from infrastructure.ai.dashscope_embeddings import DashScopeEmbeddings


class VectorStoreRepository:
    """
     作用：对向量数据库做场景读写

    """

    def __init__(self):
        """
        创建向量数据库实例
        创建嵌入模型的实例
        向量数据库能力: 1.存储向量数据 2.搜索能力（向量数据库检索器）
        """
        # 使用自定义的 DashScopeEmbeddings 替代 OpenAIEmbeddings 以解决格式不兼容问题
        self.embedding = DashScopeEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.API_KEY
        )

        self.vector_database = Chroma(
            persist_directory=settings.VECTOR_STORE_PATH,
            collection_name="its-knowledge",
            embedding_function=self.embedding
        )


    def  add_documents(self,documents:list,batch_size:int=16)->int:
        """
        将切分之后的文档块保存到向量数据库中

        Args:
            documents: 切分之后的文档块
            batch_size: 分批保存文档块的批次大小

        Returns:
            int:成功添加到向量数据库中文档块的数量(服务前端展示)

        """

        # 1. 获取到文档块的总数量
        total_documents_chunks=len(documents)

        # 2. 分批次保存
        documents_chunks_added=0
        try:
            for i in range(0,total_documents_chunks,batch_size):
                batch=documents[i:batch_size+i]
                self.vector_database.add_documents(batch)
                documents_chunks_added=documents_chunks_added+len(batch)
                logger.info(f"成功将文档块:{documents_chunks_added}/{total_documents_chunks}保存到向量数据库...")
            return documents_chunks_added
        except Exception as e:
            logger.error(f"文档保存到向量数据库失败: {str(e)}")
            raise e

    def title_exists(self, title: str) -> bool:
        """检查指定标题的文档是否已入库(用于上传接口的同名文档提示)"""
        try:
            result = self.vector_database._collection.get(where={"title": title}, limit=1)
            return bool(result and result.get("ids"))
        except Exception as e:
            logger.error(f"查询文档是否存在失败: {str(e)}")
            return False

    def delete_by_title(self, title: str):
        """
        根据标题删除向量数据库中的相关文档块
        """
        try:
            # Chroma 允许通过 metadata 过滤删除
            self.vector_database.delete(where={"title": title})
            logger.info(f"已从向量数据库中删除标题为 '{title}' 的所有文档块")
        except Exception as e:
            logger.error(f"从向量数据库删除文档失败: {str(e)}")



    async def embedd_document(self, text: str) -> List[float]:
        """
          对query进行向量化 (异步)
        Args:
            text: 输入文本

        Returns:
            List[float]: 嵌入后的浮点数列表

        """
        # DashScopeEmbeddings 目前主要支持同步，但在 async 环境中调用是安全的
        return self.embedding.embed_query(text)

    async def embedd_documents(self, texts: List[str]) -> List[List[float]]:
        """
        对字符串列表进行向量化 (异步)
        Args:
         texts: 输入文本字符串列表

        Returns:
            List[List[float]]: 嵌入后的多个文本的浮点数列表

        """
        return self.embedding.embed_documents(texts)

    async def search_similarity_with_score(self, user_question: str, top_k: int = 8) -> List[tuple[Document, float]]:
        """
         相似性检索带文档分数 (异步)
         分数（chroma向量数据库）：返回是L2距离得分（分数值越小越相似），不是余弦相似度的得分（分数余额高越相似） 距离得分：1-余弦相似度得分
        Args:
            user_question:
            top_k: 返回结果数量

        Returns:
            List[tuple[Document, float]]: 返回基于向量检索的相似性文档列表及其得分
        """
        # 使用 aio 版本的相似度搜索
        return await self.vector_database.asimilarity_search_with_score(user_question, k=top_k)





















