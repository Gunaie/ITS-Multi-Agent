from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from config.settings import settings

# 阿里百炼配置
AL_BAILIAN_API_KEY = settings.AL_BAILIAN_API_KEY
AL_BAILIAN_BASE_URL = settings.AL_BAILIAN_BASE_URL
MAIN_MODEL_NAME = settings.MAIN_MODEL_NAME
SUB_MODEL_NAME = settings.SUB_MODEL_NAME

# 创建模型客户端
# 主模型客户端(协调Agent使用)
main_model_client = AsyncOpenAI(
    base_url=AL_BAILIAN_BASE_URL,
    api_key=AL_BAILIAN_API_KEY
)
# 子模型客户端(干活的子Agent使用)
sub_model_client = AsyncOpenAI(
    base_url=AL_BAILIAN_BASE_URL,
    api_key=AL_BAILIAN_API_KEY
)




# 创建主调度模型
main_model = OpenAIChatCompletionsModel(
    model=MAIN_MODEL_NAME,
    openai_client=main_model_client)

# 创建子调度模型
sub_model = OpenAIChatCompletionsModel(
    model=SUB_MODEL_NAME,
    openai_client=sub_model_client)
