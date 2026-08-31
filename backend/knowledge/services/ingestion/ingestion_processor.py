import os
import logging
from langchain_text_splitters import MarkdownTextSplitter
from repositories.vector_store_repository import VectorStoreRepository
from repositories.file_repository import FileRepository
from config.settings import settings
from langchain_core.documents import Document

from common.infrastructure.logging.logger import logger

class IngestionProcessor:
    def __init__(self):
        self.vector_store = VectorStoreRepository()
        self.file_repo = FileRepository()
        self.document_spliter = MarkdownTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP
        )

    def ingest_file(self, file_path: str) -> int:
        """
        处理单个文件的入库，包含去重逻辑和多格式支持
        """
        try:
            title = os.path.basename(file_path)
            
            # 1. 去重逻辑：如果已存在，先删除旧的
            self.vector_store.delete_by_title(title)
            
            documents = []
            
            # 2. 根据文件类型选择加载方式
            if file_path.endswith('.md'):
                # Markdown 特殊处理
                content = self.file_repo.read_file_content(file_path)
                if not content:
                    return 0
                chunks = self.document_spliter.split_text(content)
                for i, chunk in enumerate(chunks):
                    documents.append(Document(
                        page_content=f"文档来源:{title}\n{chunk}",
                        metadata={"path": file_path, "title": title, "chunk_index": i}
                    ))
            elif file_path.endswith(('.pdf', '.docx', '.txt')):
                # 轻量加载器 (无 torch/CUDA/opencv 依赖)
                from langchain_community.document_loaders import (
                    PyPDFLoader, Docx2txtLoader, TextLoader
                )
                if file_path.endswith('.pdf'):
                    loader = PyPDFLoader(file_path)
                elif file_path.endswith('.docx'):
                    loader = Docx2txtLoader(file_path)
                else:
                    loader = TextLoader(file_path)
                raw_docs = loader.load()

                from langchain_text_splitters import RecursiveCharacterTextSplitter
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP
                )
                chunks = splitter.split_documents(raw_docs)

                for i, chunk in enumerate(chunks):
                    chunk.page_content = f"文档来源:{title}\n{chunk.page_content}"
                    chunk.metadata.update({"path": file_path, "title": title, "chunk_index": i})
                    documents.append(chunk)
            elif file_path.endswith('.doc'):
                logger.warning(f"不支持 .doc 旧格式，请转换为 .docx 后再上传: {file_path}")
                return 0
            else:
                logger.warning(f"不支持的文件格式: {file_path}")
                return 0

            # 3. 保存到向量数据库
            if not documents:
                return 0
                
            added_count = self.vector_store.add_documents(documents)
            logger.info(f"文件 {title} 入库成功，共 {added_count} 个分块")
            return added_count

        except Exception as e:
            logger.error(f"文件入库失败: {file_path}, 错误: {str(e)}")
            raise e
