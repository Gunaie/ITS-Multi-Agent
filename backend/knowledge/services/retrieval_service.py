import logging
import jieba
import re
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

        # 3.根据标题的元数据（roughing_score）排序并且留下前50个
        return sorted(mds_metadata, key=lambda x: x['roughing_score'], reverse=True)[:50]

    def fine_ranking(self, user_query: str, rough_mds_metadata: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
         对标题进行精排
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
            query_embedding = self.chroma_vector.embedd_document(user_query)

            # 3. 获取粗排后的标题
            roughing_title = [md_metadata['title'] for md_metadata in rough_mds_metadata]

            # 4. 标题的向量值
            roughing_title_embeddings = self.chroma_vector.embedd_documents(roughing_title)

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

    def retrieval(self, user_question: str) -> List[Document]:
        """
        核心检索方法：多路检索 + 重排序
        """
        if not user_question:
            return []

        # 1. 执行多路并行检索 (此处为逻辑并行，实际为顺序执行)
        vector_docs = []
        try:
            vector_docs = self._search_based_vector(user_question)[:5]
        except Exception as e:
            logger.error(f"向量检索失败: {e}")

        title_docs = []
        try:
            title_docs = self._search_based_title(user_question)
        except Exception as e:
            logger.error(f"标题检索失败: {e}")

        # 2. 合并、去重与截断
        all_docs = vector_docs + title_docs
        if not all_docs:
            logger.warning(f"所有检索路径均未找到内容: {user_question}")
            return []

        unique_docs = self._deduplicate(all_docs)

        # 3. 粗排 (语义打分)
        try:
            rough_top_docs = self._reranking(unique_docs[:15], user_question)
        except Exception as e:
            logger.error(f"语义粗排失败: {e}")
            rough_top_docs = unique_docs[:10]

        # 4. 精排 (LLM 重排序)
        try:
            if len(rough_top_docs) > 1:
                final_docs = self.query_service.rerank_documents(user_question, rough_top_docs[:6])
            else:
                final_docs = rough_top_docs
            return final_docs[:4]
        except Exception as e:
            logger.error(f"LLM精排失败: {e}")
            return rough_top_docs[:4]

    def _search_based_vector(self, user_question: str) -> List[Document]:
        """
        第一路检索
        基于语义相似度检索

        Args:
            user_question: 用户输入的问题

        Returns:
            List[Document]： Top-N个相似的文档列表

        """
        # 1.返回带分数的文档列表
        documents_with_score = self.chroma_vector.search_similarity_with_score(user_question)

        # 2.TODO(不用距离得分)
        based_vector_candidates = []
        for document, _ in documents_with_score:
            based_vector_candidates.append(document)
        return based_vector_candidates

    def _search_based_title(self, user_query: str) -> List[Document]:
        """
         第二路检索
         基于标题的关键词匹配检索
        Args:
            user_query: 用户输入的问题

        Returns:
            List[Document]: Top-N个相似的文档列表

        """

        # 1. 从缓存获取元数据
        mds_metadata = self._get_cached_metadata()

        # 2. 进行标题匹配
        # 2.1 关键词匹配（jieba）--->（比较对象：用户输入的问题 vs crawl目录下的文件标题）
        # 2.2 标题的语义匹配（比较对象：用户的输入问题  vs md目录下的 ）
        rough_mds_metadata = self.rough_ranking(user_query, mds_metadata)
        fine_mds_metadata = self.fine_ranking(user_query, rough_mds_metadata)

        # 3. 处理文档（根据标题读取标题对于的文档内容---Document(page_content,metadata={})）

        based_title_candidates = []
        for fine_md_metadata in fine_mds_metadata:
            file_path = fine_md_metadata.get('path')
            if not file_path:
                continue
                
            try:
                import os
                if not os.path.exists(file_path):
                    logger.warning(f"Metadata references non-existent file: {file_path}. Skipping.")
                    continue

                # 3.1 打开文件
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                # 3.2 判断content内容长度
                # a.短md知识
                if len(content) < 3000:
                    # 不切分
                    doc = Document(page_content=content, metadata={
                        "path": file_path,
                        "title": fine_md_metadata.get('title', 'Unknown'),
                    })
                    based_title_candidates.append(doc)
                # b. 长md知识 切分
                else:
                    doc_chunks = self._deal_long_title_content(content, fine_md_metadata, user_query)
                    based_title_candidates.extend(doc_chunks)
            except Exception as e:
                logger.error(f"Error processing document {file_path}: {e}")
                # 继续处理下一个文档，而不是中断整个流程
                continue
        # 4. 返回指定文档列表
        return based_title_candidates

    def _deduplicate(self, total_candidates: List[Document]) -> List[Document]:
        """
         对合并后的文档列表去重
         用set()集合去重（(title,内容的前【100】个字符)）-->key
        Args:
            total_candidates: 合并的文档列表

        Returns:
            List[Document]：唯一的文档列表
        """

        if not total_candidates:
            return []

        # 2. 定义set集合
        seen = set()
        unique_candidates = []

        # 3. 遍历合并后的每一个文档列表
        for document in total_candidates:
            # 去重（）
            # 使用更安全的提取逻辑
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

        # 4. 返回唯一的
        return unique_candidates

    def _reranking(self, unique_candidates: List[Document], user_question: str) -> List[Document]:
        """
         重新计算打分&&排序
         第二路长文档已经进行了cosine_similarity()的计算（无需在次打分）
         对第一路的文档和第二路的短文档进行重新计算

        Args:
            unique_candidates: 唯一的候选文档列表
            user_question: 用户输入的问题

        Returns:
            List[Document]: 最终指定Top-N的文档列表

        """

        # 1. 判断去重合并之后文档列表是否有文档对象
        if not unique_candidates:
            return []

        need_embedding_docs = []
        need_embedding_candidates_indices = []
        score_doc = []

        # 2. 遍历去重并合并之后的文档列表(Document,score)
        for candidate_index, unique_candidate in enumerate(unique_candidates):
            # 如何去判断 第二路长文档 or  第一路的文档和第二路?
            # 2.1 第二路的长文档
            if "similarity" in unique_candidate.metadata:
                score_doc.append((unique_candidate, unique_candidate.metadata['similarity']))
            # 2.2 第一路和第二路的短文档
            else:
                need_embedding_docs.append(unique_candidate)
                need_embedding_candidates_indices.append(candidate_index)

        # 3.处理需要重新计算分数的文档
        if need_embedding_docs:
            # 3.1 计算用户问题的向量
            query_embedding = self.chroma_vector.embedd_document(user_question)

            # 3.2 获取到需要向量的文档内容
            # 注意：doc.page_content 已经包含了 "文档来源:title\n" 前缀，无需重复添加
            embedding_docs_content = [doc.page_content for doc in need_embedding_docs]
            
            # 3.3 计算需要向量的文档内容
            doc_embeddings = self.chroma_vector.embedd_documents(embedding_docs_content)

            # 3.4 计算相似得分
            similarity = cosine_similarity([query_embedding], doc_embeddings).flatten()

            # 3.5 封装到带得分的文档列表
            for idx, doc in enumerate(need_embedding_docs):
                score_doc.append((doc, similarity[idx]))

        # 4. 排序
        sorted_docs = sorted(score_doc, key=lambda x: x[1], reverse=True)

        # 5. 返回更多候选给 LLM Rerank (增加到 10 个)
        return [doc for doc, _ in sorted_docs[:10]]

    def _deal_long_title_content(self, content: str, fine_md_metadata: Dict[str, Any], user_query: str) -> List[
        Document]:
        """
         处理标题对应的长文本
         切分-->文档块--->算文档块和问题的相似度
        Args:
            content: 长文本
            fine_md_metadata: 长文本对应的元数据
            user_query: 用户的问题

        Returns:
            List[Document]: 和问题相似的文档块（chunk）
        """

        # 1. 对长文本切分(换成适合)
        chunks = self.spliter.document_spliter.split_text(content)

        # 2. 获取对应的标题
        doc_chunks_title = fine_md_metadata['title']

        # 3. 标题注入到文档块中（第二次结构和第一次的拼接一定要一样）TODO
        doc_chunks_inject_title = [f"文档来源:{doc_chunks_title}" + doc_chunk for doc_chunk in chunks]

        # 4. 对问题向量
        query_embedding = self.chroma_vector.embedd_document(user_query)

        # 5. 对切分后的文档块向量化
        doc_chunk_embeddings = self.chroma_vector.embedd_documents(doc_chunks_inject_title)

        # 6. 计算相似性:doc_chunks_similarity[0.8,0.6,0.7,0.1,0.9]
        doc_chunks_similarity = cosine_similarity([query_embedding], doc_chunk_embeddings).flatten()

        # 7. 获取3个相似性分数值高的三个索引 argsort->[3,1,2,0,4]->[2,0,4]--->[4,0,2]
        top_doc_chunks_indices = doc_chunks_similarity.argsort()[-3:][::-1]

        # 8. 构建最终文档对象列表(为每一个切分后的块)
        docs = []
        for i, chunk_idx in enumerate(top_doc_chunks_indices):
            doc = Document(
                page_content=doc_chunks_inject_title[chunk_idx],  # 带上
                metadata={
                    "path": fine_md_metadata['path'],
                    "title": fine_md_metadata['title'],
                    "chunk_index": int(chunk_idx),
                    "similarity": float(doc_chunks_similarity[chunk_idx])
                }
            )
            docs.append(doc)

        return   docs


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
