from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from config.settings import settings

# 阿里百炼配置
AL_BAILIAN_API_KEY = settings.AL_BAILIAN_API_KEY
AL_BAILIAN_BASE_URL = settings.AL_BAILIAN_BASE_URL
ORCHESTRATOR_MODEL_NAME = settings.ORCHESTRATOR_MODEL_NAME
TECHNICAL_MODEL_NAME = settings.TECHNICAL_MODEL_NAME
SERVICE_MODEL_NAME = settings.SERVICE_MODEL_NAME

# 共享模型客户端（百炼 OpenAI 兼容端点）
_model_client = AsyncOpenAI(
    base_url=AL_BAILIAN_BASE_URL,
    api_key=AL_BAILIAN_API_KEY,
)

# 调度Agent模型（路由决策/handoff 判断）
orchestrator_model = OpenAIChatCompletionsModel(
    model=ORCHESTRATOR_MODEL_NAME,
    openai_client=_model_client,
)

# 技术专家模型（知识整合 + 联网搜索结果融合）
technical_model = OpenAIChatCompletionsModel(
    model=TECHNICAL_MODEL_NAME,
    openai_client=_model_client,
)

# 服务专家模型（百度地图工具调用为主）
service_model = OpenAIChatCompletionsModel(
    model=SERVICE_MODEL_NAME,
    openai_client=_model_client,
)
