"""

创建FastAPI实例 并且管理所有的路由

"""
import logging
logger=logging.getLogger(__name__)
import os
import sys

# 将项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 强制设置 sys.stdout 编码为 utf-8 以防止 Windows 下的 UnicodeEncodeError
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import  uvicorn
from fastapi import FastAPI
from api.routers import router
def  create_fast_api()->FastAPI:


    # 1. 创建FastApi实例
    app=FastAPI(title="Knowledge API")


    # 2. 注册各种路由
    app.include_router(router=router)

    # 3.返回创建的FastAPI
    return app

app = create_fast_api()

if __name__ == '__main__':
    print("1.准备启动Web服务器")
    try:
        uvicorn.run(app=app,host="127.0.0.1",port=8001)
        logger.info("2.启动Web服务器成功...")
    except KeyboardInterrupt as e:
        logger.error(f"2.启动Web服务器失败: {str(e)}")














