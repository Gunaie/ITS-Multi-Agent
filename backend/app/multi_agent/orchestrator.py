from agents import Agent, ModelSettings, Runner, function_tool, Session, RunContextWrapper, handoff
from infrastructure.ai.openai_client import main_model, sub_model
from infrastructure.ai.prompt_loader import load_prompt
from multi_agent.technical_agent import technical_agent
from multi_agent.service_agent import comprehensive_service_agent
from infrastructure.tools.mcp.mcp_servers import search_mac_client, amap_map_mcp

from common.infrastructure.logging.logger import logger

async def on_handoff_technical(ctx: RunContextWrapper):
    logger.info(f"Orchestrator: Handing off to Technical Expert")
    # 检查核心 MCP 服务是否就绪
    if not technical_agent.mcp_servers:
        logger.warning("Technical Expert has no MCP servers connected. Performance may be degraded.")

async def on_handoff_service(ctx: RunContextWrapper):
    logger.info(f"Orchestrator: Handing off to Service Expert")
    # 检查核心 MCP 服务是否就绪
    if not comprehensive_service_agent.mcp_servers:
        logger.warning("Service Expert has no MCP servers connected. Location services may be unavailable.")

# 定义 Orchestrator Agent
orchestrator_agent = Agent(
    name="智能调度专家",
    instructions=load_prompt("orchestrator"),
    model=sub_model, # 使用更快的 Flash 模型进行路由决策
    model_settings=ModelSettings(temperature=0),
    handoffs=[
        handoff(
            technical_agent, 
            on_handoff=on_handoff_technical,
            tool_name_override="consult_technical_expert"
        ),
        handoff(
            comprehensive_service_agent, 
            on_handoff=on_handoff_service,
            tool_name_override="query_service_station_and_navigate"
        )
    ],
)
