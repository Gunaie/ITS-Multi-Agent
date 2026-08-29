"""
应用配置管理模块

使用 pydantic-settings 进行配置管理，支持：
1. 自动从环境变量读取配置
2. 类型验证和转换
3. 默认值设置
4. 配置文档化
"""
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing_extensions import Self


from common.config.base_settings import BaseCommonSettings

class Settings(BaseCommonSettings):
    """
    应用配置类
    """
    # ==================== 模型配置 ====================

    MAIN_MODEL_NAME: Optional[str] = Field(
        default="qwen3.8-27b",
        description="主模型名称"
    )
    SUB_MODEL_NAME: Optional[str] = Field(
        default="qwen3.7-flash-2026-07-15",
        description="子模型名称"
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

    # ==================== 外部服务配置 ====================

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

    # ==================== Pydantic Settings 配置 ====================

    model_config = SettingsConfigDict(
        # 计算.env文件的绝对路径：config目录的父目录(app目录)下的.env
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",          # .env文件编码
        case_sensitive=True,                 # 环境变量名大小写敏感
        extra="ignore",                      # 忽略额外的环境变量
        validate_default=True,               # 验证默认值
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

