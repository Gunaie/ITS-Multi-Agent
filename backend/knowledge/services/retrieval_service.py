import logging
import jieba
import re
import os
import asyncio
from typing import List, Dict, Any, Optional

# 使用统一的 logger，移除重复的 basicConfig
from common.infrastructure.logging.logger import logger

from langchain_core.documents import Document
from repositories.vector_store_repository import VectorStoreRepository
from services.ingestion.ingestion_processor import IngestionProcessor
from utils.markdown_utils import MarkDownUtils
from services.query_service import QueryService
from config.settings import settings
from sklearn.metrics.pairwise import cosine_similarity


class RetrievalService:
    """
    负责检索的类（检索器）
    """
    
    # 类级别的元数据缓存，避免频繁磁盘扫描
    _metadata_cache: Optional[List[Dict[str, Any]]] = None
    _last_cache_time: float = 0
    CACHE_TTL = 300 # 5分钟缓存过期

    def __init__(self):
        self.chroma_vector = VectorStoreRepository()
        self.spliter = IngestionProcessor()
        self.query_service = QueryService()
        
        # 加载自定义词典提升技术名词识别率
        dict_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dict.txt")
        if os.path.exists(dict_path):
            logger.info(f"Loading custom jieba dictionary from {dict_path}")
            jieba.load_userdict(dict_path)

    def _get_cached_metadata(self) -> List[Dict[str, Any]]:
        """获取或更新元数据缓存"""
        import time
        now = time.time()
        if not self._metadata_cache or (now - self._last_cache_time) > self.CACHE_TTL:
            logger.info("Refreshing knowledge base metadata cache...")
            self._metadata_cache = MarkDownUtils.collect_md_metadata(settings.CRAWL_OUTPUT_DIR)
            self._last_cache_time = now
        return self._metadata_cache

    def rough_ranking(self, user_query, mds_metadata: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
         对标题进行粗排
         基于jieba进行标题的分词匹配
        Args:
            user_query: 用户的问题
            mds_metadata: 所有md的元数据（标题【title】，路径【path】）

        Returns:
            List[Dict[str,Any]]:所有md的元数据 （标题【title】，路径【path】，标题粗排得分【rough_score】）
        """

        # 1. 用户输入问题是否存在
        if not user_query:
            return []
        ROUGHIN_WORD_WEIGHT = 0.7

        # 2.遍历mds_metadata(所有md的元数据)
        for md_metadata in mds_metadata:
            # 2.1 获取md标题
            md_metadata_title = md_metadata['title']

            # 2.2 判断标题是否存在
            if not md_metadata_title and not md_metadata_title.strip():
                continue
            # 2.3 进行分词&&算得分
            # 2.3.1 优先用字符切:set:交、并、差:jarcard算法=A N B/A U B
            user_query_char = set(user_query)
            md_metadata_title_char = set(md_metadata_title)
            unique_char = user_query_char | md_metadata_title_char
            char_score = len(user_query_char & md_metadata_title_char) / len(unique_char) if len(unique_char) > 0 else 0

            # 2.3.2 在用jieba词项切(影响因素大一些)
            user_query_word = set(jieba.lcut(user_query))
            md_metadata_title_word = set(jieba.lcut(md_metadata_title))
            unique_word = user_query_word | md_metadata_title_word
            word_score = len(user_query_word & md_metadata_title_word) / len(unique_word) if len(unique_word) > 0 else 0

            # 2.3.3 计算粗排分数：字符级+词性项级(侧重)
            roughing_score = word_score * ROUGHIN_WORD_WEIGHT + char_score * (1 - ROUGHIN_WORD_WEIGHT)

            md_metadata['roughing_score'] = float(roughing_score)

        # 3.根据标题的元数据（roughing_score）排序并且留下前 N 个
        return sorted(mds_metadata, key=lambda x: x['roughing_score'], reverse=True)[:settings.TOP_ROUGH]

    async def fine_ranking(self, user_query: str, rough_mds_metadata: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
         对标题进行精排 (异步)
         基于嵌入模型相似性以及cosine_similarity()
        Args:
            user_query: 用户当前问题
            rough_mds_metadata: 粗排后的md元数据

        Returns:
            List[Dict[str, Any]]: 带精排分数的元数据
        """

        # 1. 判粗排元数据
        if not rough_mds_metadata:
            return []

        try:
            # 2. 对问题向量化
            query_embedding = await self.chroma_vector.embedd_document(user_query)

            # 3. 获取粗排后的标题
            roughing_title = [md_metadata['title'] for md_metadata in rough_mds_metadata]

            # 4. 标题的向量值
            roughing_title_embeddings = await self.chroma_vector.embedd_documents(roughing_title)

            # 5. 计算问题和粗排标题的相似度
            similarity = cosine_similarity([query_embedding], roughing_title_embeddings).flatten()
            
            ROUGH_HEIGHT = 0.3
            SIM_HEIGHT = 0.7
            for index, md_metadata in enumerate(rough_mds_metadata):
                sim = max(0, similarity[index])
                roughing_score = md_metadata.get('roughing_score', 0)
                final_score = roughing_score * ROUGH_HEIGHT + sim * SIM_HEIGHT
                md_metadata['sim_score'] = sim
                md_metadata['final_score'] = final_score
        except Exception as e:
            logger.error(f"精排向量计算失败: {e}。退化为粗排分数。")
            for md_metadata in rough_mds_metadata:
                md_metadata['sim_score'] = 0
                md_metadata['final_score'] = md_metadata.get('roughing_score', 0)

        # 7. 排序
        sim_mds_metadata = sorted(rough_mds_metadata, key=lambda x: x.get('final_score', 0), reverse=True)[:5]

        # 8. 返回
        return sim_mds_metadata

    async def retrieval(self, user_question: str) -> List[Document]:
        """
        核心检索方法：多路异步并行检索 + 重排序
        """
        if not user_question:
            return []

        # 1. 执行多路异步并行检索
        # 使用 asyncio.gather 实现真正的并行
        try:
            vector_task = self._search_based_vector(user_question)
            title_task = self._search_based_title(user_question)
            
            vector_docs, title_docs = await asyncio.gather(vector_task, title_task)
            
            vector_docs = vector_docs[:5]
        except Exception as e:
            logger.error(f"多路检索发生错误: {e}")
            vector_docs = []
            title_docs = []

        # 2. 合并、去重与截断
        all_docs = vector_docs + title_docs
        if not all_docs:
            logger.warning(f"所有检索路径均未找到内容: {user_question}")
            return []

        unique_docs = self._deduplicate(all_docs)

        # 3. 粗排 (语义打分)
        try:
            # 限制候选数量以提升速度
            rough_top_docs = await self._reranking(unique_docs[:15], user_question)
        except Exception as e:
            logger.error(f"语义重排序失败: {e}")
            rough_top_docs = unique_docs[:10]

        # 4. 精排 (LLM 重排序已禁用以提升速度，直接返回语义排序 Top 4)
        return rough_top_docs[:4]

    async def _search_based_vector(self, user_question: str) -> List[Document]:
        """
        第一路检索：基于语义相似度检索 (异步)
        """
        # 1.返回带分数的文档列表
        documents_with_score = await self.chroma_vector.search_similarity_with_score(user_question)

        # 2.提取文档对象
        based_vector_candidates = []
        for document, _ in documents_with_score:
            based_vector_candidates.append(document)
        return based_vector_candidates

    async def _search_based_title(self, user_query: str) -> List[Document]:
        """
         第二路检索：基于标题的关键词匹配检索 (异步)
        """

        # 1. 从缓存获取元数据
        mds_metadata = self._get_cached_metadata()

        # 2. 进行标题匹配
        rough_mds_metadata = self.rough_ranking(user_query, mds_metadata)
        fine_mds_metadata = await self.fine_ranking(user_query, rough_mds_metadata)

        # 3. 处理文档
        based_title_candidates = []
        for fine_md_metadata in fine_mds_metadata:
            file_path = fine_md_metadata.get('path')
            if not file_path:
                continue
                
            try:
                if not os.path.exists(file_path):
                    logger.warning(f"Metadata references non-existent file: {file_path}. Skipping.")
                    continue

                # 3.1 打开文件 (由于是本地文件且量小，同步读取通常足够快，但大量并发时可考虑 aiofiles)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                
                # 3.2 判断content内容长度
                if len(content) < 3000:
                    doc = Document(page_content=content, metadata={
                        "path": file_path,
                        "title": fine_md_metadata.get('title', 'Unknown'),
                    })
                    based_title_candidates.append(doc)
                else:
                    doc_chunks = await self._deal_long_title_content(content, fine_md_metadata, user_query)
                    based_title_candidates.extend(doc_chunks)
            except Exception as e:
                logger.error(f"Error processing document {file_path}: {e}")
                continue
        return based_title_candidates

    def _deduplicate(self, total_candidates: List[Document]) -> List[Document]:
        """
         对合并后的文档列表去重
        """
        if not total_candidates:
            return []

        seen = set()
        unique_candidates = []

        for document in total_candidates:
            content = document.page_content
            if content.startswith("文档来源:"):
                parts = content.split("\n", 1)
                clean_content = parts[1].strip() if len(parts) > 1 else ""
            else:
                clean_content = content.strip()
            
            key = (document.metadata['title'], clean_content[:100])
            if key not in seen:
                seen.add(key)
                unique_candidates.append(document)

        return unique_candidates

    async def _reranking(self, unique_candidates: List[Document], user_question: str) -> List[Document]:
        """
         重新计算打分&&排序 (异步)
        """

        if not unique_candidates:
            return []

        need_embedding_docs = []
        need_embedding_candidates_indices = []
        score_doc = []

        for candidate_index, unique_candidate in enumerate(unique_candidates):
            if "similarity" in unique_candidate.metadata:
                score_doc.append((unique_candidate, unique_candidate.metadata['similarity']))
            else:
                need_embedding_docs.append(unique_candidate)
                need_embedding_candidates_indices.append(candidate_index)

        if need_embedding_docs:
            query_embedding = await self.chroma_vector.embedd_document(user_question)
            embedding_docs_content = [doc.page_content for doc in need_embedding_docs]
            doc_embeddings = await self.chroma_vector.embedd_documents(embedding_docs_content)
            similarity = cosine_similarity([query_embedding], doc_embeddings).flatten()

            for idx, doc in enumerate(need_embedding_docs):
                score_doc.append((doc, similarity[idx]))

        sorted_docs = sorted(score_doc, key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in sorted_docs[:10]]

    async def _deal_long_title_content(self, content: str, fine_md_metadata: Dict[str, Any], user_query: str) -> List[Document]:
        """
         处理标题对应的长文本 (异步)
        """
        chunks = self.spliter.document_spliter.split_text(content)
        doc_chunks_title = fine_md_metadata['title']
        doc_chunks_inject_title = [f"文档来源:{doc_chunks_title}\n" + doc_chunk for doc_chunk in chunks]

        query_embedding = await self.chroma_vector.embedd_document(user_query)
        doc_chunk_embeddings = await self.chroma_vector.embedd_documents(doc_chunks_inject_title)
        doc_chunks_similarity = cosine_similarity([query_embedding], doc_chunk_embeddings).flatten()

        top_doc_chunks_indices = doc_chunks_similarity.argsort()[-3:][::-1]

        docs = []
        for i, chunk_idx in enumerate(top_doc_chunks_indices):
            doc = Document(
                page_content=doc_chunks_inject_title[chunk_idx],
                metadata={
                    "path": fine_md_metadata['path'],
                    "title": fine_md_metadata['title'],
                    "chunk_index": int(chunk_idx),
                    "similarity": float(doc_chunks_similarity[chunk_idx])
                }
            )
            docs.append(doc)

        return docs


if __name__ == '__main__':
    retrival_service = RetrievalService()

    # rough_ranking_result = retrival_service.rough_ranking("我的电脑开机之后没有任何的反应"）
    # for roughing_result in rough_ranking_result[:10]:
    #     print(f"粗排---{roughing_result}")
    #
    # sim_ranking_result = retrival_service.fine_ranking("我的电脑开机之后没有任何的反应", rough_ranking_result[:10])
    #
    # for sim_result in sim_ranking_result:
    #     print(f"精排---{sim_result}")

    # result = retrival_service.retrieval("我的电脑开机之后没有任何的反应")
    # result = retrival_service.retrieval("如何安装联想的一件影音")
    # result = retrival_service.retrieval("联想手机K900常见问题汇总有哪些")
    # result = retrival_service.retrieval("如何使用U盘安装Windows 7操作系统.")
    # result = retrival_service.retrieval("开机屏幕黑屏或蓝屏报错,无法正常进入系统怎么办")
    # result = retrival_service.retrieval("我的电脑经常死机该如何解决")
    result = retrival_service.retrieval("手机、平板上的画面能无线传输到电视上播放吗") # 80-90%

    for r in result:
        print(r)
