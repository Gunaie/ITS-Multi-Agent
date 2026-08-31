from agents import Agent, ModelSettings, Runner, function_tool, Session, RunContextWrapper, handoff
from infrastructure.ai.openai_client import orchestrator_model
from infrastructure.ai.prompt_loader import load_prompt
from multi_agent.technical_agent import technical_agent
from multi_agent.service_agent import comprehensive_service_agent
from infrastructure.tools.mcp.mcp_servers import search_mac_client

from common.infrastructure.logging.logger import logger

async def on_handoff_technical(ctx: RunContextWrapper):
    logger.info(f"Orchestrator: Handing off to Technical Expert")
    # 检查核心 MCP 服务是否就绪
    if not technical_agent.mcp_servers:
        logger.info("Technical Expert has no MCP servers connected. Using built-in web_search fallback.")
    tool_names = [getattr(t, "name", None) or getattr(t, "__name__", repr(t)) for t in (technical_agent.tools or [])]
    mcp_names = [s.name for s in (technical_agent.mcp_servers or [])]
    logger.info(f"Technical Expert runtime state: tools={tool_names}, mcp_servers={mcp_names}")

async def on_handoff_service(ctx: RunContextWrapper):
    logger.info(f"Orchestrator: Handing off to Service Expert")
    try:
        tools = comprehensive_service_agent.tools or []
        tool_names = [
            getattr(t, "name", None) or getattr(t, "__name__", repr(t))
            for t in tools
        ]
        mcp_names = [s.name for s in (comprehensive_service_agent.mcp_servers or [])]
        logger.info(
            f"Service Expert runtime state: tools={tool_names}, mcp_servers={mcp_names}"
        )
        # 额外输出会话快照以便诊断"位置无法确定"
        session = getattr(ctx, "context", None)
        if session is not None:
            try:
                items = await session.get_items() if hasattr(session, "get_items") else getattr(session, "items", [])
            except Exception:
                items = getattr(session, "items", [])
            last_user = ""
            for it in reversed(items or []):
                role = ""
                content = ""
                if isinstance(it, dict):
                    role = it.get("role", "")
                    content = str(it.get("content", ""))
                else:
                    role = getattr(it, "role", "")
                    content = str(getattr(it, "content", ""))
                if role == "user":
                    last_user = content
                    break
            try:
                ctx_dict = session.context if isinstance(session.context, dict) else {}
            except Exception:
                ctx_dict = {}
            logger.info(
                f"Service Expert session snapshot: last_user_text={last_user!r}, "
                f"context={dict(ctx_dict)}"
            )
    except Exception as e:
        logger.warning(f"Failed to snapshot Service Expert state at handoff: {e}")

# 定义 Orchestrator Agent
orchestrator_agent = Agent(
    name="智能调度专家",
    instructions=load_prompt("orchestrator"),
    model=orchestrator_model, # 调度者用强模型做路由决策/handoff 判断
    model_settings=ModelSettings(temperature=0),
    handoffs=[
        handoff(
            technical_agent,
            on_handoff=on_handoff_technical,
            tool_name_override="consult_technical_expert",
            tool_description_override=(
                "交接给技术咨询专家。触发条件：硬件故障（蓝屏/黑屏/死机/开机无反应/异响/过热）、"
                "软件操作（安装/设置/驱动/系统）、错误代码、性能问题、实时资讯（天气/新闻/新品/价格）。"
                "若用户同时提出维修站等线下服务诉求，仍先交接本工具处理技术部分。"
            ),
        ),
        handoff(
            comprehensive_service_agent,
            on_handoff=on_handoff_service,
            tool_name_override="query_service_station_and_navigate",
            tool_description_override=(
                "交接给业务服务专家，查询真实门店数据。触发条件：用户提到维修站/服务站/服务网点/门店/"
                "售后点/线下服务/导航，或询问'附近的X'/'哪里能修X'/'XX在哪'，或催问此前承诺过的门店查询结果。"
                "用户未提供位置时也必须交接（工具内置定位解析与追问链路）。"
                "注意：门店信息只能由本工具的真实查询产生，交接前严禁自行编造任何地址或电话。"
            ),
        )
    ],
)
