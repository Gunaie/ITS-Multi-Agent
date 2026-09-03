"""
应用配置管理模块

使用 pydantic-settings 进行配置管理，支持：
1. 自动从环境变量读取配置
2. 类型验证和转换
3. 默认值设置
4. 配置文档化
"""
import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing_extensions import Self


class Settings(BaseSettings):
    """
    应用配置类

    配置项会自动从以下来源读取（优先级从高到低）：
    1. 环境变量
    2. .env 文件
    3. 默认值
    """

    # ==================== AI 服务配置 ====================

    # 阿里百炼 API
    AL_BAILIAN_API_KEY: Optional[str] = Field(default=None, description="阿里百炼 API Key")
    AL_BAILIAN_BASE_URL: Optional[str] = Field(default=None, description="阿里百炼 Base URL")

    # ==================== 模型配置 ====================

    ORCHESTRATOR_MODEL_NAME: Optional[str] = Field(
        default="qwen3.7-max-2026-06-08",
        description="调度Agent(orchestrator)模型名称"
    )
    TECHNICAL_MODEL_NAME: Optional[str] = Field(
        default="qwen3.8-max-0902",
        description="技术专家(technical)模型名称"
    )
    SERVICE_MODEL_NAME: Optional[str] = Field(
        default="deepseek-v4-flash-0731",
        description="服务专家(service)模型名称"
    )

    # ==================== 数据库配置 ====================

    MYSQL_HOST: Optional[str] = Field(default="localhost", description="MySQL主机地址")
    MYSQL_PORT: int = Field(default=3306, description="MySQL端口")
    MYSQL_USER: Optional[str] = Field(default="root", description="MySQL用户名")
    MYSQL_PASSWORD: Optional[str] = Field(default="", description="MySQL密码")
    MYSQL_DATABASE: Optional[str] = Field(default="its_db", description="MySQL数据库名")
    MYSQL_CHARSET: str = Field(default="utf8mb4", description="MySQL字符集")
    MYSQL_CONNECT_TIMEOUT: int = Field(default=10, description="MySQL连接超时（秒）")
    MYSQL_MAX_CONNECTIONS: int = Field(default=5, description="MySQL最大连接数")

    REDIS_HOST: str = Field(default="localhost", description="Redis主机地址")
    REDIS_PORT: int = Field(default=6379, description="Redis端口")

    # ==================== 外部服务配置 ====================
    BAIDU_MAP_AK: Optional[str] = Field(default=None, description="百度地图 API AK(服务端类型,geocode/Place等Web服务使用)")
    BAIDU_MAP_AK_BROWSER: Optional[str] = Field(default=None, description="百度地图 AK(浏览器端类型,前端 JS API 浏览器定位专用)")

    # 知识库服务
    KNOWLEDGE_BASE_URL: Optional[str] = Field(
        default=None,
        description="知识库服务URL"
    )

    # 通义千问搜索服务
    DASHSCOPE_BASE_URL: Optional[str] = Field(
        default=None,
        description="通义千问 DashScope Base URL"
    )

    # ==================== 会话历史压缩配置 ====================
    SESSION_COMPRESS_THRESHOLD: int = Field(
        default=24,
        description="会话历史条目数超此值触发摘要压缩（≈12轮对话）"
    )
    SESSION_COMPRESS_KEEP_RECENT: int = Field(
        default=10,
        description="压缩时保留最近N条原文（5轮user+assistant）"
    )

    # ==================== LangChain / LangSmith 可观测性配置 ====================
    LANGCHAIN_TRACING_V2: str = Field(default="false", description="是否开启 LangSmith 追踪")
    LANGCHAIN_ENDPOINT: Optional[str] = Field(default="https://api.smith.langchain.com", description="LangSmith 端点")
    LANGCHAIN_API_KEY: Optional[str] = Field(default=None, description="LangSmith API Key")
    LANGCHAIN_PROJECT: Optional[str] = Field(default="its-multi-agent", description="LangSmith 项目名称")

    # ==================== Pydantic Settings 配置 ====================

    model_config = SettingsConfigDict(
        # 依次寻找 .env 文件：当前目录 -> app目录 -> backend目录 -> 项目根目录
        env_file=[
            os.path.join(os.path.dirname(__file__), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env"),
        ],
        env_file_encoding="utf-8",          # .env文件编码
        case_sensitive=True,                 # 环境变量名大小写敏感
        extra="ignore",                      # 忽略额外的环境变量
        validate_default=True                # 验证默认值
    )

    # ====================  ====================
    @model_validator(mode='after')
    def check_ai_service_configuration(self) -> Self:
        """
        验证器：在配置加载完成后自动执行。
        如果需要强制至少配置一个 AI 服务，可以在这里抛出 ValueError
        """
        # 注意：这里 self 已经是实例化后的模型对象
        has_service = all([
            self.AL_BAILIAN_API_KEY,
            self.AL_BAILIAN_BASE_URL
        ])

        if not has_service:
            raise ValueError("必须配置阿里百炼 API 服务 (API_KEY 和 BASE_URL)")

        return self



# 创建全局配置实例
settings = Settings()

# 将 LangSmith 相关的配置应用到环境变量中，供底层库使用
if settings.LANGCHAIN_TRACING_V2.lower() == "true":
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    if settings.LANGCHAIN_ENDPOINT:
        os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
    if settings.LANGCHAIN_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    if settings.LANGCHAIN_PROJECT:
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    print(f"LangSmith Tracing Enabled: Project={settings.LANGCHAIN_PROJECT}")

