"""

创建FastAPI实例 并且管理所有的路由

"""
import logging
import os
import sys
from contextlib import asynccontextmanager

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 强制设置 sys.stdout 编码为 utf-8 以防止 Windows 下 the UnicodeEncodeError
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from api.routers import router

from common.infrastructure.logging.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Knowledge API starting up...")
    yield
    # Shutdown logic
    logger.info("Knowledge API shutting down...")

def create_fast_api() -> FastAPI:
    # 1. 创建FastApi实例
    app = FastAPI(title="Knowledge API", lifespan=lifespan)

    # 2. 全局异常处理
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.error(f"Validation error for {request.url.path}: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "请求参数验证失败", "errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception in Knowledge API: {str(exc)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "知识库服务繁忙，请稍后再试。"},
        )

    # 3. 注册各种路由
    app.include_router(router=router)

    return app

app = create_fast_api()

if __name__ == '__main__':
    print("1.准备启动Web服务器 (开发模式 - 热重载已开启)")
    try:
        # 注意：使用 reload=True 时必须传入字符串形式的 app 路径
        # 且需要在 backend/knowledge 目录下运行，或者正确设置 PYTHONPATH
        uvicorn.run("api.main:app", host="127.0.0.1", port=8001, reload=True)
        logger.info("2.启动Web服务器成功...")
    except KeyboardInterrupt as e:
        logger.error(f"2.启动Web服务器失败: {str(e)}")














