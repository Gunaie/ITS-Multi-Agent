import os
import logging
import aiofiles
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from services.ingestion.ingestion_processor import IngestionProcessor
from schemas.schema import UploadResponse, QueryResponse, QueryRequest
from services.retrieval_service import RetrievalService
from services.query_service import QueryService
from config.settings import settings

from common.infrastructure.logging.logger import logger

# 创建路由和实例
router = APIRouter()
ingestion_processor = IngestionProcessor()
retrieval_service = RetrievalService()
query_service = QueryService()


@router.get("/health", summary="健康检查")
async def health():
    return {"status": "ok"}

@router.post("/upload", response_model=UploadResponse, summary="处理知识库上传")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    处理文件上传并异步入库
    """
    try:
        # 0. 文件格式白名单校验
        ALLOWED_EXTENSIONS = {'.md', '.pdf', '.docx', '.txt'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件格式: {file_ext}，仅支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        # 0.5 同名文档检测: 已存在同名文档则提示将覆盖更新(入库本身为幂等覆盖)
        doc_exists = ingestion_processor.vector_store.title_exists(file.filename)

        # 1. 准备保存目录
        temp_md_dir = settings.TMP_MD_FOLDER_PATH
        os.makedirs(temp_md_dir, exist_ok=True)
        
        file_path = os.path.join(temp_md_dir, file.filename)
        
        # 2. 保存上传文件到磁盘
        async with aiofiles.open(file_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):
                await out_file.write(content)
        
        # 3. 注册后台任务进行入库处理
        # 这样 API 可以立即返回，不用等待耗时的向量化过程
        background_tasks.add_task(ingestion_processor.ingest_file, file_path)

        if doc_exists:
            return UploadResponse(
                status="updated",
                message=f"检测到同名文档「{file.filename}」已存在，本次上传将覆盖更新旧版本",
                file_name=file.filename,
                chunks_added=0
            )
        return UploadResponse(
            status="success",
            message="文件上传成功，正在后台处理入库...",
            file_name=file.filename,
            chunks_added=0
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")

@router.post("/query", response_model=QueryResponse, summary="查询知识库")
async def query(request: QueryRequest):
    """
    查询知识库
    """
    try:
        # 1. 判断用户问题
        user_question = request.question
        if not user_question:
            raise HTTPException(status_code=400, detail="查询问题不能为空")

        # 2. 调用检索器的检索方法 (异步)
        retrieval_context = await retrieval_service.retrieval(user_question)

        # 3. 调用查询器的查询方法 (异步)
        answer = await query_service.generate_answer(user_question, retrieval_context)

        # 4. 封装到响应数据模型
        return QueryResponse(
            question=user_question,
            answer=answer
        )
    except Exception as e:
        logger.error(f"调用查询知识库服务失败:原因:{str(e)}")
        raise HTTPException(status_code=500, detail=f"服务内部出现异常: {str(e)}")
