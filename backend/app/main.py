import os
import sys

# 立即设置 Python 路径以支持 common 和内部模块
# 使用绝对路径以确保在不同工作目录下都能正确识别
current_file_path = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file_path)
parent_dir = os.path.dirname(current_dir)

# 强制插入路径，确保优先级
sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)

from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import json
import asyncio
import re
from agents import Runner, RunConfig
from common.infrastructure.logging.logger import logger
from multi_agent.orchestrator import orchestrator_agent
from multi_agent.service_agent import comprehensive_service_agent
from common.infrastructure.auth.router import router as auth_router
from common.infrastructure.auth.models import UserRepo
from common.infrastructure.auth.deps import get_current_user
from common.infrastructure.limiter import limiter
from config.settings import settings
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# 强制设置 sys.stdout 编码为 utf-8 以防止 Windows 下的 UnicodeEncodeError
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

app = FastAPI(title="ITS Multi-Agent Application Backend")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error for {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": str(exc.body)},
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "智能体系统繁忙，请稍后再试。"},
    )

# 注册 Auth 路由
app.include_router(auth_router)

from infrastructure.tools.mcp.mcp_servers import search_mac_client, baidu_map_mcp
from infrastructure.tools.local.location_service import parse_frontend_location
from multi_agent.technical_agent import technical_agent
from multi_agent.service_agent import comprehensive_service_agent

# 初始化数据库表与 MCP 服务
@app.on_event("startup")
async def startup_event():
    try:
        UserRepo.init_table()
        logger.info("Database tables initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}")
    
    # 预连接 MCP 服务并注入子智能体，使用异步任务防止阻塞启动
    async def init_mcp():
        logger.info("Starting background MCP connection task...")

        # 如果两个 MCP 都没配，直接跳过
        if search_mac_client is None and baidu_map_mcp is None:
            disabled = []
            if search_mac_client is None:
                disabled.append("MCP search client disabled (no valid AL_BAILIAN_API_KEY)")
            if baidu_map_mcp is None:
                disabled.append("BaiduMap MCP disabled (no valid BAIDU_MAP_AK)")
            logger.info("; ".join(disabled) + ". Skipping MCP connection.")
            logger.info("Background MCP connection task finished.")
            return

        for i in range(3):
            try:
                # 超时时间：内部 httpx 已自带超时，外层留足 20s 余量
                async def connect_safe(client, name):
                    if client is None:
                        return None  # 表示此客户端未配置，不计失败
                    try:
                        await asyncio.wait_for(client.connect(), timeout=20.0)
                        logger.info(f"Successfully connected to MCP {name} service.")
                        return True
                    except Exception as e:
                        error_detail = str(e)
                        if hasattr(e, "exceptions"):
                            error_detail = "; ".join([str(ex) for ex in e.exceptions])
                        # 最后一次重试仍然失败才使用 WARNING，其余用 INFO
                        level = logger.warning if i == 2 else logger.info
                        level(f"MCP {name} connection attempt {i+1}/3 failed: {error_detail}")
                        return False

                results = await asyncio.gather(
                    connect_safe(search_mac_client, "Search"),
                    connect_safe(baidu_map_mcp, "BaiduMap"),
                    return_exceptions=True,
                )

                def resolve_bool(r):
                    if r is None: return None  # 未配置
                    if isinstance(r, bool): return r
                    return False

                search_ok = resolve_bool(results[0])
                baidu_ok = resolve_bool(results[1])

                any_ready = False
                if search_ok:
                    technical_agent.mcp_servers = [search_mac_client]
                    # MCP 主搜索就绪时移除本地兜底工具：两个相似搜索工具并存会让模型
                    # 确定性误选兜底工具（temperature=0），摘除后无从误选
                    technical_agent.tools = [
                        t for t in technical_agent.tools if t.name != "builtin_web_search"
                    ]
                    any_ready = True
                if baidu_ok:
                    comprehensive_service_agent.mcp_servers = [baidu_map_mcp]
                    any_ready = True

                if any_ready or (search_ok is None and baidu_ok is None):
                    ready_msgs = []
                    if search_ok:
                        ready_msgs.append("Search MCP ready")
                    elif search_ok is None:
                        ready_msgs.append("Search MCP skipped (no key)")
                    if baidu_ok:
                        ready_msgs.append("BaiduMap MCP ready")
                    elif baidu_ok is None:
                        ready_msgs.append("BaiduMap MCP skipped (no key)")
                    logger.info("MCP services are ready: " + ", ".join(ready_msgs) + ".")
                    break
            except Exception as e:
                logger.error(
                    f"MCP connection iteration {i+1} encountered unexpected error: {e}"
                )

            await asyncio.sleep(2)

        # 循环结束后记录最终状态（优雅降级 INFO，不打 WARNING）
        unavailable = []
        if search_mac_client is not None and not technical_agent.mcp_servers:
            unavailable.append("search")
        if baidu_map_mcp is not None and not comprehensive_service_agent.mcp_servers:
            unavailable.append("baidu_map")
        if unavailable:
            logger.info(
                f"MCP service(s) not available after retries: {', '.join(unavailable)}. "
                "Agent(s) will fall back to built-in tools."
            )
        logger.info("Background MCP connection task finished.")

    asyncio.create_task(init_mcp())

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from typing import Optional

class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"
    location: Optional[str] = None
    app_type: str = "agent"  # agent (咨询平台) 或 knowledge (管理平台)

class ChatResponse(BaseModel):
    answer: str

# 分布式会话存储 (使用 Redis)
from agents.memory import Session
from infrastructure.database.redis_client import redis_client, binary_redis_client
from infrastructure.database.session_impl import SimpleSession
import pickle
import time

# 统一文本提取逻辑
def extract_text(obj, include_reasoning=False):
    if not obj: return ""
    if isinstance(obj, str): return obj
    if isinstance(obj, list): return "".join([extract_text(i, include_reasoning) for i in obj])
    
    res = ""
    reasoning_attr = None
    content_attr = None
    
    # 1. 尝试获取 content 和 reasoning (处理 OpenAI 风格对象)
    content_attr = getattr(obj, "content", None)
    reasoning_attr = getattr(obj, "reasoning_content", None)
    
    # 2. 处理 ResponseOutputText / ResponseOutputMessage / ResponseOutputReasoningText 等新类型
    if not content_attr:
        content_attr = getattr(obj, "text", None)
    if not reasoning_attr:
        reasoning_attr = getattr(obj, "reasoning", None)
        
    # 3. 处理字典格式
    if isinstance(obj, dict):
        content_attr = content_attr or obj.get("content")
        reasoning_attr = reasoning_attr or obj.get("reasoning_content") or obj.get("reasoning")
        # 处理 choices 结构 (ChatCompletion 或 ChatCompletionChunk)
        if "choices" in obj and len(obj["choices"]) > 0:
            choice = obj["choices"][0]
            delta = choice.get("delta", {})
            message = choice.get("message", {})
            content_attr = content_attr or delta.get("content") or message.get("content")
            reasoning_attr = reasoning_attr or delta.get("reasoning_content") or message.get("reasoning_content")
    
    # 4. 处理 ChatCompletionChunk / ChatCompletion 对象
    if hasattr(obj, "choices") and len(obj.choices) > 0:
        choice = obj.choices[0]
        if hasattr(choice, "delta"):
            content_attr = content_attr or getattr(choice.delta, "content", None)
            reasoning_attr = reasoning_attr or getattr(choice.delta, "reasoning_content", None)
        elif hasattr(choice, "message"):
            content_attr = content_attr or getattr(choice.message, "content", None)
            reasoning_attr = reasoning_attr or getattr(choice.message, "reasoning_content", None)

    if include_reasoning and reasoning_attr:
        res += f"**[思考过程]**\n{reasoning_attr}\n\n---\n\n"
    
    if content_attr:
        if isinstance(content_attr, str):
            res += content_attr
        else:
            # 可能是列表或其他对象，递归提取
            res += extract_text(content_attr, include_reasoning)
            
    # 备选：text 属性 (兜底)
    if not res and not reasoning_attr:
        text = getattr(obj, "text", None) or (obj.get("text") if isinstance(obj, dict) else None)
        if text: res = str(text)
        
    return res

def get_session(session_id: str) -> Session:
    session_data = binary_redis_client.get(f"session:{session_id}")
    if session_data:
        try:
            return pickle.loads(session_data)
        except Exception as e:
            logger.error(f"Error loading session from redis: {e}")

    # 如果不存在或加载失败，创建新会话
    new_session = SimpleSession(session_id=session_id)
    return new_session

def extract_client_ip(request: Request) -> str:
    """提取客户端真实公网 IP（供 IP 定位兜底使用），私网 IP 由定位服务侧过滤"""
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else ""
    if not ip and request.client:
        ip = request.client.host or ""
    return ip.strip()

# 问题文本中的地点窄提取: 仅匹配"我在/位于 X"句式（用户回答定位追问的典型形态），
# 且排除常见动词开头（我在想/我在用...），避免误提取。提取结果会经地理编码校验，失败自动降级。
_LOCATION_IN_TEXT_RE = re.compile(
    r"(?:^|[，。！？,.\s])(?:我在|我位于|我目前在|位于)([\u4e00-\u9fa5A-Za-z0-9]{2,25})"
)
_LOCATION_VERB_PREFIXES = ("想", "觉得", "需", "打", "担", "怀", "考", "看", "听", "用", "做", "写")


def apply_location_to_session(session: Session, request: Request, location: Optional[str],
                              question: str = "") -> None:
    """
    将前端定位信息归一化后写入会话上下文。
    location 契约:
    - "lat,lng"            -> 默认 BD-09 坐标
    - "wgs84:lat,lng"/"gps:lat,lng"   -> GPS 原始坐标，自动转 BD-09
    - "gcj02:lat,lng"                 -> 高德/腾讯坐标，自动转 BD-09
    - "bd09:lat,lng"                  -> 百度坐标
    - 地址文本（如 "武汉光谷"）        -> location_hint_pending，由工具侧惰性 geocode
    location 字段缺失时，尝试从问题文本中窄提取"我在X"式地点（同样写入 location_hint_pending）。
    同时捕获客户端 IP 供 IP 定位兜底使用。
    """
    session.context["client_ip"] = extract_client_ip(request)
    if location and location.strip():
        coords = parse_frontend_location(location)
        if coords:
            import time as _time
            session.context["location_record"] = {
                "coords": coords,
                "source": "frontend_gps",
                "display": "",
                "ts": _time.time(),
            }
            # 新的 GPS 定位覆盖旧的待解析文本
            session.context.pop("location_hint_pending", None)
        else:
            session.context["location_hint_pending"] = location.strip()
        return
    # location 字段缺失 -> 从问题文本窄提取（典型场景: 用户用一句话回答"您在哪个城市"的追问）
    m = _LOCATION_IN_TEXT_RE.search(question or "")
    if m and not m.group(1).startswith(_LOCATION_VERB_PREFIXES):
        session.context["location_hint_pending"] = m.group(1)


# ----------------------------- 意图网关（确定性路由） -----------------------------
# 背景: temperature=0 的 Flash 调度模型在多轮服务场景中不稳定——会复读追问文案、
# 嘴上说"正在查询"却不交接、甚至编造结果。对"短句 + 明确服务意图"的高频高危意图,
# 绕过调度者直连业务服务专家（工具链路自带追问与防编造约束）; 复合/模糊意图仍走调度者。
_SERVICE_INTENT_RE = re.compile(
    r"维修站|服务站|服务网点|维修点|门店|售后|授权服务|网点|附近的|哪里能修|怎么去"
)
_SERVICE_CONT_RE = re.compile(r"找到了吗|找到了没|查到了吗|结果呢|有了吗")
_DIRECT_ROUTE_MAX_LEN = 30
# 复合意图保护: 句子同时含技术故障关键词时不直连服务（让调度者先处理技术部分）
_TECH_KEYWORDS_RE = re.compile(
    r"蓝屏|黑屏|死机|开机|没反应|进水|噪音|清理|更新|卡顿|重启|不能开机|无法开机|不开机"
)
# 恶意/异常请求保护: 含编造/虚假等词时不直连服务（应被调度者拒绝）
_MALICIOUS_RE = re.compile(r"编|虚假|编造|伪造|假的|生成.*地址|编.*维修")


def should_direct_route_service(question: str, ctx: dict) -> bool:
    """短句且意图明确的服务请求 -> 直连业务服务专家。
    排除: 复合意图（含技术关键词）、恶意请求（编造虚假地址）。"""
    q = (question or "").strip()
    if not q or len(q) > _DIRECT_ROUTE_MAX_LEN:
        return False
    if not _SERVICE_INTENT_RE.search(q):
        # 追问后的确认类短句（"找到了吗"）: 仅在会话存在服务查询上下文时直连
        if _SERVICE_CONT_RE.search(q) and (
            ctx.get("location_record") or ctx.get("location_hint_pending") or ctx.get("service_query_ts")
        ):
            return True
        return False
    # 含服务关键词，但检查是否为复合意图或恶意请求
    if _TECH_KEYWORDS_RE.search(q):
        return False  # 复合意图，交调度者处理技术部分
    if _MALICIOUS_RE.search(q):
        return False  # 恶意请求，交调度者拒绝
    return True


def classify_intent(question: str, ctx: dict) -> str:
    """三分类意图网关: compound | service_only | other。

    - compound: 同时含技术故障关键词 + 服务网点关键词 -> 显式编排(先 technical 后 service)
    - service_only: 仅短句服务意图(沿用 should_direct_route_service 判定)
    - other: 单一技术意图/模糊/闲聊 -> 交调度者路由
    """
    q = (question or "").strip()
    has_tech = bool(_TECH_KEYWORDS_RE.search(q))
    has_service = bool(_SERVICE_INTENT_RE.search(q))
    if has_tech and has_service and not _MALICIOUS_RE.search(q):
        return "compound"
    if should_direct_route_service(question, ctx):
        return "service_only"
    return "other"


async def run_compound_flow(question: str, session, context) -> str:
    """复合意图显式编排: 先技术专家诊断, 后服务专家查维修站, 合并回答。

    根治 temperature=0 下调度者处理复合意图时多轮遗忘/丢半边的问题。
    technical 先跑完拿到诊断; service 跑时强制"必须且只能调用维修站查询工具"。
    """
    # 阶段1: 技术诊断。附加系统提示: 服务部分由系统自动处理, 不引导用户再问
    tech_input = f"{question}\n\n[系统提示] 维修站查询部分由系统自动处理, 你只需专注技术诊断, 不要引导用户另行查询维修站。"
    logger.info("Compound flow stage 1: Technical Expert")
    tech_result = await Runner.run(
        technical_agent,
        input=tech_input,
        session=session,
        context=context,
        run_config=RunConfig(tracing_disabled=not (settings.LANGCHAIN_TRACING_V2.lower() == "true"))
    )
    tech_answer = tech_result.final_output or ""

    # 阶段2: 维修站查询。service_agent 提示词已强制"必须且只能调用维修站查询工具"
    logger.info("Compound flow stage 2: Service Expert (repair stations)")
    svc_result = await Runner.run(
        comprehensive_service_agent,
        input=question,
        session=session,
        context=context,
        run_config=RunConfig(tracing_disabled=not (settings.LANGCHAIN_TRACING_V2.lower() == "true"))
    )
    svc_answer = svc_result.final_output or ""

    # 合并: 技术诊断 + 分隔 + 维修站结果
    merged = f"{tech_answer}\n\n---\n\n附近联想官方维修站查询结果：\n{svc_answer}"
    return merged

def save_session(session_id: str, session: Session, user_id: str = None, app_type: str = "agent"):
    try:
        # 保存会话内容 (使用 pickle 以支持 agents 库的复杂对象)
        binary_redis_client.setex(
            f"session:{session_id}",
            60 * 60 * 24 * 7,  # 延长至7天
            pickle.dumps(session)
        )
        # 如果提供了用户ID，维护用户的会话列表
        if user_id:
            # 使用有序集合存储，以时间戳排序，按 app_type 分离
            redis_client.zadd(f"user_sessions:{app_type}:{user_id}", {session_id: time.time()})
            # 记录会话的元数据（如标题）
            if not redis_client.exists(f"session_meta:{session_id}"):
                # 初始标题使用第一条提问的前15个字
                title = "新对话"
                if hasattr(session, 'items') and len(session.items) > 0:
                    first_msg = session.items[0]
                    # 使用统一的 extract_text 提取内容
                    raw_content = ""
                    if isinstance(first_msg, dict):
                        raw_content = first_msg.get("content", "")
                    elif hasattr(first_msg, "content"):
                        raw_content = first_msg.content
                    
                    content = extract_text(raw_content, include_reasoning=False)
                    if content:
                        title = content[:15] + ("..." if len(content) > 15 else "")
                
                redis_client.hset(f"session_meta:{session_id}", mapping={
                    "title": title,
                    "created_at": time.time(),
                    "app_type": app_type
                })
    except Exception as e:
        logger.error(f"Error saving session to redis: {e}")

@app.get("/sessions")
async def list_sessions(app_type: str = "agent", current_user: dict = Depends(get_current_user)):
    user_id = current_user['username'] # 使用用户名作为标识
    session_ids = redis_client.zrevrange(f"user_sessions:{app_type}:{user_id}", 0, -1)
    
    sessions = []
    for sid in session_ids:
        meta = redis_client.hgetall(f"session_meta:{sid}")
        if meta:
            sessions.append({
                "id": sid,
                "title": meta.get("title", "未知对话"),
                "created_at": float(meta.get("created_at", 0))
            })
    return sessions

@app.get("/sessions/{session_id}")
async def get_session_detail(session_id: str, current_user: dict = Depends(get_current_user)):
    session = get_session(session_id)
    history = []
    
    # SimpleSession.items 存储的是 TResponseInputItem (dict)
    if hasattr(session, 'items'):
        for item in session.items:
            role = item.get("role")
            raw_content = item.get("content")
            # 使用全局的 extract_text，包含推理过程
            content = extract_text(raw_content, include_reasoning=True)
            
            if content:
                history.append({
                    "role": role,
                    "content": content
                })
    return {"history": history}

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, app_type: str = "agent", current_user: dict = Depends(get_current_user)):
    user_id = current_user['username']
    try:
        # 从用户列表中移除
        redis_client.zrem(f"user_sessions:{app_type}:{user_id}", session_id)
        # 删除会话内容
        binary_redis_client.delete(f"session:{session_id}")
        # 删除元数据
        redis_client.delete(f"session_meta:{session_id}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail="删除会话失败")

class SessionTitleUpdate(BaseModel):
    title: str
    app_type: Optional[str] = "agent"

@app.patch("/sessions/{session_id}")
async def update_session_title(session_id: str, request: SessionTitleUpdate, current_user: dict = Depends(get_current_user)):
    try:
        app_type = request.app_type or "agent"
        logger.info(f"Updating session {session_id} (type: {app_type}) title to: {request.title}")
        meta_key = f"session_meta:{session_id}"
        
        if not redis_client.exists(meta_key):
            logger.warning(f"Session meta not found: {meta_key}")
            # 如果元数据不存在，可能是旧会话或未初始化的会话，尝试创建一个
            redis_client.hset(meta_key, mapping={
                "title": request.title,
                "created_at": time.time(),
                "app_type": app_type
            })
        else:
            # 存在则只更新标题
            redis_client.hset(meta_key, "title", request.title)
            # 同时确保它在正确的用户列表中（以防万一）
            user_id = current_user['username']
            redis_client.zadd(f"user_sessions:{app_type}:{user_id}", {session_id: time.time()})
            
        return {"status": "success", "title": request.title}
    except Exception as e:
        logger.error(f"Failed to update session title for {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新标题失败: {str(e)}")

@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request, chat_request: ChatRequest, current_user: dict = Depends(get_current_user)):
    try:
        user_id = current_user['username']
        logger.info(f"User {user_id} asked: {chat_request.question} (session: {chat_request.session_id})")
        session = get_session(chat_request.session_id)

        # 归一化定位信息（坐标/文本/问题文本窄提取 + 客户端 IP），带来源与时间戳
        apply_location_to_session(session, request, chat_request.location, chat_request.question)

        # 用户消息由 Runner.run(input=..., session=...) 自动写入会话，无需手动 add_items。
        # 此前为绕过 handoff 丢首条输入的手动添加与 SDK 自动写入叠加，导致历史中用户消息重复两遍。
        # 移除后已由 E2E 场景B/M 覆盖验证 handoff 链路正常。
            
        # 运行编排智能体，传入 session 和 context；意图网关三分支编排
        intent = classify_intent(chat_request.question, session.context)
        logger.info(f"Intent gate: {intent}")
        if intent == "service_only":
            session.context["service_query_ts"] = time.time()
            result = await Runner.run(
                comprehensive_service_agent,
                input=chat_request.question,
                session=session,
                context=session,
                run_config=RunConfig(tracing_disabled=not (settings.LANGCHAIN_TRACING_V2.lower() == "true"))
            )
            logger.info("Agent Runner finished (service_only direct route)")
        elif intent == "compound":
            merged = await run_compound_flow(chat_request.question, session, session)
            result = type("R", (), {"final_output": merged})()  # 轻量结果对象
            logger.info("Agent Runner finished (compound orchestrated)")
        else:
            result = await Runner.run(
                orchestrator_agent,
                input=chat_request.question,
                session=session,
                context=session,
                run_config=RunConfig(tracing_disabled=not (settings.LANGCHAIN_TRACING_V2.lower() == "true"))
            )
            logger.info("Agent Runner finished (orchestrator route)")
        
        # 保存会话状态到 Redis，传入 user_id 以便列出 (增加 app_type 支持)
        save_session(chat_request.session_id, session, user_id=user_id, app_type=chat_request.app_type)

        return ChatResponse(answer=result.final_output)
    except Exception as e:
        logger.error(f"Error in chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"智能体执行失败: {str(e)}")

@app.post("/chat_knowledge", response_model=ChatResponse)
async def chat_knowledge(request: Request, chat_request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    专门为管理平台提供的严格基于知识库的对话接口
    """
    try:
        user_id = current_user['username']
        session = get_session(chat_request.session_id)
        
        # 手动添加用户消息到 Session (管理平台不使用 Runner，需要手动维护)
        await session.add_items([{"role": "user", "content": chat_request.question}])
        
        # 直接调用知识库工具的原始函数 (严格 RAG)
        from infrastructure.tools.local.knowledge_base import query_knowledge
        try:
            if hasattr(query_knowledge, "__wrapped__"):
                answer = await query_knowledge.__wrapped__(chat_request.question)
            else:
                answer = await query_knowledge(chat_request.question)
        except Exception as tool_err:
            logger.error(f"Knowledge tool call failed: {tool_err}")
            answer = f"抱歉，检索知识库时发生错误: {str(tool_err)}"
        
        # 手动添加助手消息到 Session
        await session.add_items([{"role": "assistant", "content": answer}])
        
        # 保存会话
        save_session(chat_request.session_id, session, user_id=user_id, app_type=chat_request.app_type)
        
        return ChatResponse(answer=answer)
    except Exception as e:
        logger.error(f"Error in chat_knowledge: {str(e)}")
        raise HTTPException(status_code=500, detail="查询知识库失败")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/chat_stream")
async def chat_stream(request: Request, chat_request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    流式对话接口 (SSE)
    """
    async def event_generator():
        try:
            user_id = current_user['username']
            logger.info(f"User {user_id} asked (stream): {chat_request.question} (session: {chat_request.session_id})")
            session = get_session(chat_request.session_id)

            # 归一化定位信息（坐标/文本/问题文本窄提取 + 客户端 IP），带来源与时间戳
            apply_location_to_session(session, request, chat_request.location, chat_request.question)

            # 用户消息由 Runner.run_streamed(input=..., session=...) 自动写入会话（防重复，见 /chat 注释）

            # 意图网关三分支编排（与 /chat 保持一致）
            intent = classify_intent(chat_request.question, session.context)
            logger.info(f"Intent gate (stream): {intent}")
            if intent == "service_only":
                session.context["service_query_ts"] = time.time()
                starting_agent = comprehensive_service_agent
            else:
                starting_agent = orchestrator_agent  # compound 和 other 都先走 orchestrator/technical
            stream = Runner.run_streamed(
                starting_agent,
                input=chat_request.question,
                session=session,
                context=session,
                run_config=RunConfig(tracing_disabled=not (settings.LANGCHAIN_TRACING_V2.lower() == "true"))
            )
            
            full_reasoning = ""
            # 为了在 SSE 中优雅处理超时，我们使用 asyncio.timeout 包装整个生成逻辑
            # glm-5.2 工具调用循环（知识库检索+联网搜索）需要更长时间，超时提至 120s
            try:
                async with asyncio.timeout(120.0):
                    async for event in stream.stream_events():
                        # 根据事件类型封装成 SSE 格式
                        event_type = str(event.type)
                        if "." in event_type: # 处理 Enum 字符串，如 "EventType.run_item_stream_event" -> "run_item_stream_event"
                            event_type = event_type.split(".")[-1]
                            
                        event_data = {
                            "type": event_type,
                        }
                        
                        # 核心逻辑：处理流式输出项目
                        if event_type == "run_item_stream_event":
                            if not hasattr(event, "item") or not event.item:
                                continue
                            
                            event_data["name"] = str(getattr(event, "name", ""))
                            item = event.item
                            item_type = str(item.type)
                            if "." in item_type:
                                item_type = item_type.split(".")[-1]
                            event_data["item_type"] = item_type
                            
                            if item_type == "message_output_item":
                                # 消息内容输出 (通常是最终完整消息)
                                # 注意：为了避免与 raw_response_event 中的实时 delta 重复导致前端显示双倍内容，
                                # 我们在此处仅记录日志，不重复发送 content 给前端。
                                # 除非 raw_response_event 没有触发（非流式情况），但 run_streamed 通常都会触发 delta。
                                raw = item.raw_item
                                logger.debug(f"Final message item received: {type(raw)}")
                                    
                            elif item_type == "tool_call_item":
                                tool_name = ""
                                raw_item = item.raw_item
                                if hasattr(raw_item, "function"):
                                    tool_name = raw_item.function.get("name", "")
                                elif hasattr(raw_item, "name"):
                                    tool_name = raw_item.name
                                elif isinstance(raw_item, dict):
                                    tool_name = raw_item.get("name") or raw_item.get("function", {}).get("name", "")
                                event_data["tool_name"] = str(tool_name)
                                yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                                
                            elif item_type == "tool_call_output_item":
                                 output = ""
                                 raw_item = item.raw_item
                                 if hasattr(raw_item, "output"):
                                     output = raw_item.output
                                 elif isinstance(raw_item, dict):
                                     output = raw_item.get("output", "")
                                 event_data["output"] = str(output)
                                 yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                        
                        # 处理实时 Raw Delta (解决咨询平台无回复的关键)
                        elif event_type == "raw_response_event":
                            data = event.data
                            sub_type = getattr(data, "type", "")
                            if sub_type == "response.output_text.delta":
                                event_data["type"] = "run_item_stream_event"
                                event_data["item_type"] = "message_output_item"
                                event_data["content"] = getattr(data, "delta", "") or ""
                                yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                            elif sub_type == "response.output_reasoning_text.delta":
                                event_data["type"] = "run_item_stream_event"
                                event_data["item_type"] = "message_output_item"
                                reasoning = getattr(data, "delta", "") or ""
                                event_data["reasoning_content"] = reasoning
                                full_reasoning += reasoning
                                yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                        elif event_type == "agent_updated_stream_event":
                            if hasattr(event, "new_agent") and event.new_agent:
                                event_data["new_agent"] = str(getattr(event.new_agent, "name", "未知智能体"))
                                yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            except (asyncio.TimeoutError, TimeoutError):
                logger.error("Streaming chat timed out after 120s")
                yield f"data: {json.dumps({'type': 'error', 'message': '响应超时，请稍后重试，或换一种方式描述您的问题。'}, ensure_ascii=False)}\n\n"
            
            # 结束后，将累积的推理过程存入会话历史中最后一个助手消息，确保持久化
            if full_reasoning and hasattr(session, 'items') and len(session.items) > 0:
                last_item = session.items[-1]
                # 兼容处理字典和对象
                if isinstance(last_item, dict) and last_item.get("role") == "assistant":
                    last_item["reasoning_content"] = full_reasoning
                elif hasattr(last_item, "role") and getattr(last_item, "role") == "assistant":
                    # 如果是对象且支持动态设置属性
                    try:
                        setattr(last_item, "reasoning_content", full_reasoning)
                    except:
                        # 如果不可变，则跳过或记录日志
                        pass
            
            # 保存会话状态到 Redis (包含 app_type 分离)
            save_session(chat_request.session_id, session, user_id=user_id, app_type=chat_request.app_type)
            
            # 发送结束标记
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"Error in streaming chat: {str(e)}", exc_info=True)
            error_msg = json.dumps({"type": "error", "message": f"服务内部错误: {str(e)}"}, ensure_ascii=False)
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    print("准备启动应用后端 (开发模式 - 热重载已开启)")
    # 使用字符串路径以支持 reload=True
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
