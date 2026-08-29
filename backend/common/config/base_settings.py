from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from typing import Optional
from pathlib import Path
import os

class BaseCommonSettings(BaseSettings):
    """
    基础通用配置类
    """
    # ==================== AI 服务配置 ====================
    AL_BAILIAN_API_KEY: Optional[str] = Field(
        default=None, 
        validation_alias=AliasChoices('AL_BAILIAN_API_KEY', 'API_KEY')
    )
    AL_BAILIAN_BASE_URL: Optional[str] = Field(
        default=None, 
        validation_alias=AliasChoices('AL_BAILIAN_BASE_URL', 'BASE_URL')
    )
    
    @property
    def API_KEY(self):
        return self.AL_BAILIAN_API_KEY
        
    @property
    def BASE_URL(self):
        return self.AL_BAILIAN_BASE_URL
    
    # 数据库配置 (通用)
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    
    # JWT 配置
    JWT_SECRET_KEY: str = Field(default="your-secret-key-here-for-dev-only")
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 7)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )
