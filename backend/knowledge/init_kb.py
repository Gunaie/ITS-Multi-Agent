
import os
import sys
import asyncio
import logging

# 设置日志级别，减少噪音
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 将项目根目录添加到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from services.ingestion.ingestion_processor import IngestionProcessor
from config.settings import settings

async def init_kb():
    print(f"开始初始化知识库，扫描目录: {settings.MD_FOLDER_PATH}")
    processor = IngestionProcessor()
    
    if not os.path.exists(settings.MD_FOLDER_PATH):
        print(f"错误: 目录 {settings.MD_FOLDER_PATH} 不存在")
        return

    files = sorted([f for f in os.listdir(settings.MD_FOLDER_PATH) if f.endswith('.md')])
    print(f"找到 {len(files)} 个 Markdown 文件")

    count = 0
    for filename in files:
        file_path = os.path.join(settings.MD_FOLDER_PATH, filename)
        try:
            print(f"正在入库: {filename}...")
            processor.ingest_file(file_path)
            count += 1
        except Exception as e:
            print(f"入库失败 {filename}: {e}")
    
    print(f"初始化完成，共入库 {count} 个文件")

if __name__ == "__main__":
    asyncio.run(init_kb())
