import logging
import jieba
import re
import os
import json
import asyncio
from typing import List, Dict, Any, Optional

# 使用统一的 logger，移除重复的 basicConfig
from common.infrastructure.logging.logger import logger

from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
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
        # LLM 相关性剔除用的快模型（非思考，标题级判别 0.6s 级）
        self._rerank_llm = ChatOpenAI(
            model_name=settings.RERANK_MODEL,
            openai_api_key=settings.API_KEY,
            openai_api_base=settings.BASE_URL,
            temperature=0,
            timeout=30,
        )
        
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
            # 爬虫文档目录 + 上传文档临时目录都需要扫描，
            # 否则通过 /upload 上传的文档在标题检索路永久不可见
            metadata = MarkDownUtils.collect_md_metadata(settings.CRAWL_OUTPUT_DIR)
            tmp_dir = os.path.abspath(settings.TMP_MD_FOLDER_PATH)
            crawl_dir = os.path.abspath(settings.CRAWL_OUTPUT_DIR)
            if tmp_dir != crawl_dir:
                metadata.extend(MarkDownUtils.collect_md_metadata(tmp_dir))
            self._metadata_cache = metadata
            self._last_cache_time = now
        return self._metadata_cache

    @classmethod
    def invalidate_metadata_cache(cls):
        """失效标题元数据缓存（入库后调用，下次检索强制重新扫描磁盘）"""
        cls._metadata_cache = None
        cls._last_cache_time = 0

    def refresh_after_ingestion(self):
        """
        入库完成后调用：重建向量库句柄并失效标题缓存，
        确保新上传文档对双路检索立即可见。
        """
        try:
            self.chroma_vector.reload()
        except Exception as e:
            logger.error(f"入库后向量索引刷新失败: {e}")
        self.invalidate_metadata_cache()
        logger.info("入库后检索视图刷新完成（向量句柄已重建、标题缓存已失效）")

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
        # 注意：mds_metadata 是类级共享缓存，必须操作副本写入分数，
        # 否则并发查询会互相污染 roughing_score（A 问题的分数写进 B 问题的候选）
        ranked_results = []
        for md_metadata in mds_metadata:
            md_metadata = dict(md_metadata)
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
            ranked_results.append(md_metadata)

        # 3.根据标题的元数据（roughing_score）排序并且留下前 N 个
        return sorted(ranked_results, key=lambda x: x['roughing_score'], reverse=True)[:settings.TOP_ROUGH]

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
            
            vector_docs = vector_docs[:8]
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
            rough_top_docs = await self._reranking(unique_docs[:20], user_question)
        except Exception as e:
            logger.error(f"语义重排序失败: {e}")
            rough_top_docs = unique_docs[:10]

        # 4. 精排 (LLM 重排序已禁用以提升速度，直接返回语义排序 Top 4)
        # 同一文档（规范化 title 相同）只保留得分最高的一个 chunk，确保返回多文档覆盖
        seen_titles = set()
        final_docs = []
        for doc in rough_top_docs:
            norm_title = re.sub(r'^\d+-', '', doc.metadata.get('title', '')).replace('.md', '').strip()
            if norm_title not in seen_titles:
                seen_titles.add(norm_title)
                final_docs.append(doc)
        final_docs = final_docs[:4]

        # 5. 相似度阈值过滤：剔除弱相关候选，提升检索精度
        final_docs = self._similarity_filter(final_docs)

        # 6. 产品类目错配守卫：PC 域问题剔除明确属电视/手机/平板等的跨产品文档
        final_docs = self._product_guard(user_question, final_docs)

        # 7. LLM 相关性剔除：解决主题漂移（相似度无法区分的弱相关文档）
        return await self._llm_relevance_filter(user_question, final_docs)

    def _similarity_filter(self, docs: List[Document]) -> List[Document]:
        """
        相似度阈值过滤：低于 CONTEXT_SIM_THRESHOLD 的候选视为弱相关并剔除。
        兜底策略：
        - 若全部被过滤但最高分 >= CONTEXT_SIM_HARD_FLOOR，保留最高分单条（弱相关总比空上下文好）；
        - 若最高分也低于硬地板，判定知识库无相关内容，返回空列表，
          避免把 0337 这类完全无关的文档喂给生成环节造成误导。
        """
        if not docs:
            return []
        threshold = settings.CONTEXT_SIM_THRESHOLD
        relevant = [doc for doc in docs if doc.metadata.get('similarity', 0) >= threshold]
        if not relevant:
            best_score = docs[0].metadata.get('similarity', 0)
            if best_score < settings.CONTEXT_SIM_HARD_FLOOR:
                logger.warning(
                    f"全部候选低于相似度阈值 {threshold}，且最高分 {best_score:.3f} "
                    f"低于硬地板 {settings.CONTEXT_SIM_HARD_FLOOR}，判定知识库无相关内容，返回空上下文"
                )
                return []
            logger.warning(f"全部候选低于相似度阈值 {threshold}，兜底保留最高分文档: {docs[0].metadata.get('title')} (score={best_score:.3f})")
            relevant = docs[:1]
        return relevant

    # 产品类目关键词：标题明确命中这些类目、且查询属 PC 域时视为跨产品弱相关文档
    _PRODUCT_TITLE_KEYWORDS = {
        "电视": ("电视", "TV"),
        "手机": ("手机",),
        "平板": ("平板",),
        "打印机": ("打印机",),
        "投影": ("投影",),
    }
    # 判定查询属于 PC 域的词汇
    _PC_QUERY_KEYWORDS = (
        "笔记本", "电脑", "台式", "一体机", "Windows", "windows", "操作系统",
        "ThinkPad", "ThinkBook", "小新", "YOGA", "拯救者", "蓝屏", "黑屏", "死机", "开机",
    )

    def _product_guard(self, user_query: str, docs: List[Document]) -> List[Document]:
        """
        产品类目错配守卫（保守策略）：
        查询属 PC 域时，剔除标题明确属电视/手机/平板/打印机/投影的文档；
        若过滤后不足 2 条，按分数把被剔除的最高分文档补回，避免生成挨饿。
        """
        if not docs:
            return []
        query_lower = user_query.lower()
        query_is_pc = any(kw.lower() in query_lower for kw in self._PC_QUERY_KEYWORDS)
        if not query_is_pc:
            return docs

        kept, dropped = [], []
        for doc in docs:
            title = doc.metadata.get('title', '')
            hit_class = next(
                (class_name for class_name, keywords in self._PRODUCT_TITLE_KEYWORDS.items()
                 if any(kw in title for kw in keywords)),
                None,
            )
            if hit_class:
                dropped.append(doc)
                logger.info(f"产品类目守卫剔除文档(查询属PC域,文档属{hit_class}): {title} "
                            f"(similarity={doc.metadata.get('similarity', 0):.3f})")
            else:
                kept.append(doc)

        if len(kept) < 2 and dropped:
            rescued = sorted(dropped, key=lambda d: d.metadata.get('similarity', 0), reverse=True)[:2 - len(kept)]
            for doc in rescued:
                logger.info(f"产品类目守卫安全阀: 补回最高分被剔除文档 {doc.metadata.get('title')}")
            kept.extend(rescued)
        return kept

    async def _llm_relevance_filter(self, user_query: str, docs: List[Document]) -> List[Document]:
        """
        LLM 相关性剔除：让快模型判断每个候选标题是否有助于回答问题，只保留相关文档。
        用于解决主题漂移（如"驱动程序"检索回"花屏/黑屏"文档、相似度分数无法区分的场景）。
        失败时开放退化（保留全部），保证可用性优先。
        """
        if not settings.RERANK_ENABLED or len(docs) <= 1:
            return docs

        title_list = "\n".join(f"{i}. {doc.metadata.get('title', '')}" for i, doc in enumerate(docs))
        prompt = (
            "你是检索相关性判别器。判断每个候选文档的内容是否有助于回答用户问题。\n"
            f"【用户问题】：{user_query}\n"
            "【候选文档标题】：\n"
            f"{title_list}\n"
            '只输出 JSON，格式：{"relevant": [相关文档编号, ...]}，没有相关文档则输出 {"relevant": []}\n'
        )

        try:
            response = await self._rerank_llm.ainvoke(prompt)
            match = re.search(r'\{.*\}', response.content, re.DOTALL)
            if not match:
                logger.warning(f"LLM 相关性判别输出无法解析: {response.content[:100]}，保留全部候选")
                return docs
            relevant_ids = set(int(i) for i in json.loads(match.group()).get('relevant', []))

            kept = [doc for i, doc in enumerate(docs) if i in relevant_ids]
            dropped_titles = [doc.metadata.get('title', '') for i, doc in enumerate(docs) if i not in relevant_ids]
            if dropped_titles:
                logger.info(f"LLM 相关性剔除: {dropped_titles}")
            if not kept:
                # LLM 判定全部候选均不相关：返回空上下文，由生成环节明确告知
                # "知识库无相关方案"，不再兜底保留无关文档误导回答
                logger.warning("LLM 判定全部候选不相关，返回空上下文")
                return []
            return kept
        except Exception as e:
            logger.warning(f"LLM 相关性剔除失败({e})，保留全部候选")
            return docs

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
         规范化 title（去掉数字前缀和 .md 后缀）后再比较，避免同一文档因
         向量检索（title 带编号前缀）与标题检索（title 无前缀）两次返回
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

            norm_title = re.sub(r'^\d+-', '', document.metadata.get('title', '')).replace('.md', '').strip()
            key = (norm_title, clean_content[:100])
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
        # 将相似度分数回写 metadata，便于下游统一按分数做阈值过滤
        for doc, score in sorted_docs:
            doc.metadata['similarity'] = float(score)
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
