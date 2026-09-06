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

        self.vector_database = self._create_vector_database()

    def _create_vector_database(self):
        """创建 Chroma 持久化客户端实例"""
        return Chroma(
            persist_directory=settings.VECTOR_STORE_PATH,
            collection_name="its-knowledge",
            embedding_function=self.embedding
        )

    def reload(self):
        """
        重建底层 Chroma 客户端句柄并强制从 SQLite 重建 HNSW 索引。

        背景：chromadb 本地 PersistentClient 的 HNSW 段索引在句柄首次加载后
        长期驻留内存，同进程内其他句柄（入库写入端）新写入的向量对本句柄
        不可见；容器重启时旧进程 flush 的旧段也可能污染新进程视图（需等待
        段从 SQLite 异步重建，时机不可控）。

        本方法做三件事：
        1. clear_system_cache：清除 chromadb 按 persist 路径缓存的 System 单例；
        2. 删除磁盘上的 HNSW 段文件（保留 chroma.sqlite3 权威数据），
           强制新建客户端从 SQLite 重建段索引，杜绝"段文件与 SQLite 不一致"；
        3. 新建 Chroma 句柄。
        """
        import os
        import shutil
        import glob

        persist_path = settings.VECTOR_STORE_PATH

        # 1. 清除进程内 System 单例缓存
        try:
            from chromadb.api.client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
        except Exception as e:
            logger.warning(f"清除 chroma system cache 失败(可忽略): {e}")

        # 2. 删除磁盘 HNSW 段目录，强制从 SQLite 重建索引
        #    chromadb 的段目录是 UUID 命名，内含 data_level0.bin/header.bin 等；
        #    SQLite（chroma.sqlite3）是 embedding 的权威存储，删除段不丢数据
        deleted_segments = 0
        try:
            for entry in os.listdir(persist_path):
                entry_path = os.path.join(persist_path, entry)
                if os.path.isdir(entry_path):
                    if os.path.exists(os.path.join(entry_path, "data_level0.bin")):
                        shutil.rmtree(entry_path)
                        deleted_segments += 1
            if deleted_segments:
                logger.info(f"已删除 {deleted_segments} 个过期 HNSW 段目录，将从 SQLite 重建索引")
        except Exception as e:
            logger.error(f"删除 HNSW 段目录失败: {e}")

        # 3. 新建 Chroma 句柄（会自动从 SQLite 重建段索引）
        self.vector_database = self._create_vector_database()

        # 触发一次轻量计数，确保段索引重建完成再返回
        try:
            self.vector_database._collection.count()
        except Exception as e:
            logger.warning(f"reload 后 count 触发失败(可忽略): {e}")

        logger.info("向量库 Chroma 句柄已重建，检索视图已刷新")


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





















