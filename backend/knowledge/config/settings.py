from pydantic_settings import BaseSettings, SettingsConfigDict
from common.config.base_settings import BaseCommonSettings
import os

class Settings(BaseCommonSettings):
    MODEL: str = os.environ.get("MODEL")
    EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL")

    
    # knowledge/config
    KNOWLEDGE_BASE_URL:str=os.environ.get("KNOWLEDGE_BASE_URL")

    _current_dir = os.path.dirname(os.path.abspath(__file__))
    _knowledge_root = os.path.dirname(_current_dir)
    _backend_root = os.path.dirname(_knowledge_root)
    _project_root = os.path.dirname(_backend_root)
    
    VECTOR_STORE_PATH: str = os.path.join(_knowledge_root, "chroma_kb1")
    
    # Default directories
    CRAWL_OUTPUT_DIR: str = os.path.join(_knowledge_root, "data", "crawl")
    # Using 'data/crawl' as the default location for markdown files
    MD_FOLDER_PATH: str = CRAWL_OUTPUT_DIR
    TMP_MD_FOLDER_PATH:str= os.path.join(_knowledge_root, "data", "tmp")
    # Text splitting configuration
    CHUNK_SIZE: int = 3000
    CHUNK_OVERLAP: int = 200
    
    # Retrieval configuration
    TOP_ROUGH: int = 20
    TOP_FINAL: int = 5
    
    model_config = SettingsConfigDict(
        # 依次寻找 .env 文件：当前目录 -> knowledge目录 -> backend目录 -> 项目根目录
        env_file=[
            os.path.join(_current_dir, ".env"),
            os.path.join(_knowledge_root, ".env"),
            os.path.join(_backend_root, ".env"),
            os.path.join(_project_root, ".env"),
        ],
        env_file_encoding="utf-8",
        extra="ignore"
    )

# 必须要实例化
settings = Settings()
