import os
import sys
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import json
import asyncio
from agents import Runner, RunConfig
from common.infrastructure.logging.logger import logger
from multi_agent.orchestrator import orchestrator_agent
from common.infrastructure.auth.router import router as auth_router
from common.infrastructure.auth.models import UserRepo
from common.infrastructure.auth.deps import get_current_user
from common.infrastructure.limiter import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from contextlib import asynccontextmanager

# 将当前目录和项目根目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 强制设置 sys.stdout 编码为 utf-8 以防止 Windows 下 the UnicodeEncodeError
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from infrastructure.tools.mcp.mcp_servers import search_mac_client, amap_map_mcp
from multi_agent.technical_agent import technical_agent
from multi_agent.service_agent import comprehensive_service_agent

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    try:
        UserRepo.init_table()
        logger.info("Database tables initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}")
    
    # 预连接 MCP 服务并注入子智能体
    async def connect_with_retry(client, agent, name, max_retries=2):
        for i in range(max_retries):
            try:
                # 针对百炼平台 hosted MCP，连接可能因 SSE 握手协议不兼容而失败
                # 我们增加超时时间并捕获特定错误
                await asyncio.wait_for(client.connect(), timeout=10.0)
                if client not in agent.mcp_servers:
                    agent.mcp_servers.append(client)
                logger.info(f"Successfully connected to hosted MCP {name} service.")
                return True
            except asyncio.TimeoutError:
                logger.warning(f"Connection to MCP {name} timed out (attempt {i+1}/{max_retries})")
            except Exception as e:
                # 如果是常见的 SSE 握手错误，记录详细信息但不要让启动卡住
                wait_time = (i + 1) * 2
                logger.warning(f"MCP {name} connection issue: {str(e)}. "
                               f"Note: Bailian hosted MCPs may require specific network environments. "
                               f"Falling back to native API tools. (Attempt {i+1}/{max_retries})")
                if i < max_retries - 1:
                    await asyncio.sleep(wait_time)
        
        logger.warning(f"MCP {name} is unavailable. Using local fallback tools (DashScope Direct API).")
        return False

    async def mcp_heartbeat():
        """定期检查 MCP 连接并保活，如果掉线则尝试重连"""
        while True:
            await asyncio.sleep(300)  # 延长检查间隔至5分钟，减少对不稳连接的冲击
            try:
                # 仅在掉线时尝试重连
                if not getattr(search_mac_client, 'is_connected', False):
                     await connect_with_retry(search_mac_client, technical_agent, "Search", max_retries=1)
                if not getattr(amap_map_mcp, 'is_connected', False):
                     await connect_with_retry(amap_map_mcp, comprehensive_service_agent, "Map", max_retries=1)
            except Exception as e:
                logger.debug(f"MCP Heartbeat silent failure: {e}")

    async def init_services():
        # 并行启动连接任务
        await asyncio.gather(
            connect_with_retry(search_mac_client, technical_agent, "Search"),
            connect_with_retry(amap_map_mcp, comprehensive_service_agent, "Map")
        )
        # 启动心跳保活任务
        asyncio.create_task(mcp_heartbeat())
            
    asyncio.create_task(init_services())
    
    yield
    # Shutdown logic
    logger.info("Shutting down application...")

app = FastAPI(title="ITS Multi-Agent Application Backend", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error for {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "请求参数验证失败", "errors": exc.errors()},
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP error for {request.url.path}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception for {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
         content={"detail": "智能体系统繁忙，请稍后再试。"},
     )

# 注册 Auth 路由
app.include_router(auth_router)

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

# 统一文本提取逻辑
def extract_text(obj, include_reasoning=False):
    if not obj: return ""
    if isinstance(obj, str): return obj
    
    res = ""
    reasoning = ""
    
    if isinstance(obj, list):
        for i in obj:
            if isinstance(i, dict):
                r = i.get("reasoning_content", "")
                c = i.get("content", "")
                if r: reasoning += str(r)
                if c: res += str(c)
            else:
                res += extract_text(i)
        return f"{reasoning}\n\n{res}" if (include_reasoning and reasoning) else res

    if isinstance(obj, dict):
        # 提取思考过程
        reasoning = obj.get("reasoning_content", "")
        # 优先尝试 content 属性或字段
        content = obj.get("content")
        if content and content is not obj:
            res = extract_text(content)
        else:
            # 备选：text 属性或字段
            text = obj.get("text")
            if text: res = str(text)
            # 处理 OpenAI 风格的 delta 对象
            if "delta" in obj:
                delta = obj["delta"]
                reasoning = delta.get("reasoning_content", "")
                res = delta.get("content", "")
        
        return f"{reasoning}\n\n{res}" if (include_reasoning and reasoning) else res

    # 处理对象属性 (如 pydantic 模型)
    if hasattr(obj, "reasoning_content") and obj.reasoning_content:
        reasoning = str(obj.reasoning_content)
    
    if hasattr(obj, "content") and obj.content is not obj:
        res = extract_text(obj.content)
    elif hasattr(obj, "text"):
        res = str(obj.text)
    elif hasattr(obj, "delta"):
        delta = obj.delta
        if hasattr(delta, "reasoning_content"):
            reasoning = str(delta.reasoning_content)
        if hasattr(delta, "content"):
            res = str(delta.content)
            
    return f"{reasoning}\n\n{res}" if (include_reasoning and reasoning) else res

async def generate_title_from_llm(question: str) -> str:
    """利用 LLM 提取精简的对话标题"""
    try:
        from infrastructure.ai.openai_client import sub_model_client
        from config.settings import settings
        
        prompt = f"请为以下用户的问题提取一个极其精简的标题（不超过10个字），直接输出标题，不要包含标点符号：\n\n{question}"
        
        response = await sub_model_client.chat.completions.create(
            model=settings.SUB_MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20
        )
        title = response.choices[0].message.content.strip()
        # 移除可能的引号
        title = title.replace('"', '').replace('《', '').replace('》', '')
        return title
    except Exception as e:
        logger.warning(f"Failed to generate title via LLM: {e}")
        # 降级方案：截断原始问题
        return question[:15] + ("..." if len(question) > 15 else "")

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
            
            # 自动提取标题逻辑
            async def update_meta():
                if not redis_client.exists(f"session_meta:{session_id}"):
                    title = "新对话"
                    if hasattr(session, 'items') and len(session.items) > 0:
                        first_msg = session.items[0]
                        raw_content = ""
                        if isinstance(first_msg, dict):
                            raw_content = first_msg.get("content", "")
                        elif hasattr(first_msg, "content"):
                            raw_content = first_msg.content
                        
                        question = extract_text(raw_content)
                        if question:
                            title = await generate_title_from_llm(question)
                    
                    redis_client.hset(f"session_meta:{session_id}", mapping={
                        "title": title,
                        "created_at": time.time(),
                        "app_type": app_type
                    })
            
            # 由于 save_session 通常在同步上下文或需要快速响应的地方调用，使用 create_task
            asyncio.create_task(update_meta())
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
            # 这里改为 include_reasoning=True 以获取原汁原味的思考过程
            content = extract_text(raw_content, include_reasoning=True)
            
            if content:
                history.append({
                    "role": role,
                    "content": content
                })
    return {"history": history}

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("5/minute")
async def chat(request: Request, chat_request: ChatRequest, current_user: dict = Depends(get_current_user)):
    try:
        user_id = current_user['username']
        logger.info(f"User {user_id} asked: {chat_request.question}")
        session = get_session(chat_request.session_id)
        
        # 手动添加用户消息到 Session 以便持久化历史
        await session.add_items([{"role": "user", "content": chat_request.question}])
        
        if chat_request.location:
            session.context["user_location"] = chat_request.location
            
        # 运行编排智能体，传入 session 和 context
        result = await Runner.run(
            orchestrator_agent, 
            input=chat_request.question, 
            session=session,
            context=session,
            run_config=RunConfig(tracing_disabled=False)
        )
        # 保存会话状态到 Redis，传入 user_id 以便列出 (增加 app_type 支持)
        save_session(chat_request.session_id, session, user_id=user_id, app_type=chat_request.app_type)

        logger.info(f"Agent response generated successfully")
        return ChatResponse(answer=result.final_output)
    except Exception as e:
        logger.error(f"Error in chat: {str(e)}")
        # 即使 logger 失败（虽然不太可能，因为它用 utf-8），也不要让 print 崩溃
        try:
            print(f"Error in chat (safe print): {str(e).encode('utf-8', errors='replace').decode('utf-8')}")
        except:
            pass
        raise HTTPException(status_code=500, detail="智能体执行过程中发生错误，请稍后再试。")

from infrastructure.tools.local.knowledge_base import query_knowledge

@app.post("/chat_knowledge", response_model=ChatResponse)
async def chat_knowledge(request: Request, chat_request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    专门为管理平台提供的严格基于知识库的对话接口
    """
    try:
        user_id = current_user['username']
        session = get_session(chat_request.session_id)
        
        # 手动添加用户消息到 Session
        await session.add_items([{"role": "user", "content": chat_request.question}])
        
        # 直接调用知识库工具的原始函数 (严格 RAG)
        # 注意：query_knowledge 被 @function_tool 装饰，是一个 FunctionTool 对象
        # 使用 .__wrapped__ 获取被装饰的原始异步函数
        answer = await query_knowledge.__wrapped__(chat_request.question)
        
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
@limiter.limit("5/minute")
async def chat_stream(request: Request, chat_request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    流式对话接口 (SSE)
    """
    async def event_generator():
        user_id = current_user['username']
        session = get_session(chat_request.session_id)
        try:
            logger.info(f"User {user_id} asked (stream): {chat_request.question}")
            
            # 手动添加用户消息到 Session 以便持久化历史
            await session.add_items([{"role": "user", "content": chat_request.question}])
            
            if chat_request.location:
                session.context["user_location"] = chat_request.location
            
            # 使用 run_streamed 启动流式运行
            stream = Runner.run_streamed(
                orchestrator_agent, 
                input=chat_request.question, 
                session=session,
                context=session,
                run_config=RunConfig(tracing_disabled=False)
            )
            
            async for event in stream.stream_events():
                event_data = {
                    "type": str(event.type),
                }
                
                if event.type == "run_item_stream_event":
                    event_data["name"] = str(event.name)
                    item = event.item
                    event_data["item_type"] = str(item.type)
                    
                    if item.type == "message_output_item":
                        content = ""
                        reasoning_content = ""
                        raw = item.raw_item
                        
                        # 使用统一提取逻辑 (之前已在 event_generator 外定义或在此定义)
                        if hasattr(raw, "content") and raw.content:
                            content = extract_text(raw.content)
                        elif hasattr(raw, "choices") and len(raw.choices) > 0:
                             delta = raw.choices[0].delta
                             content = extract_text(getattr(delta, "content", ""))
                             reasoning_content = extract_text(getattr(delta, "reasoning_content", ""))
                        elif isinstance(raw, dict):
                            choices = raw.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                reasoning_content = delta.get("reasoning_content", "")
                            else:
                                content = raw.get("content", "")
                        
                        event_data["content"] = content
                        if reasoning_content:
                            event_data["reasoning_content"] = reasoning_content
                    elif item.type == "tool_call_item":
                        tool_name = ""
                        if hasattr(item.raw_item, "function"):
                            tool_name = item.raw_item.function.get("name", "")
                        elif hasattr(item.raw_item, "name"):
                            tool_name = item.raw_item.name
                        elif isinstance(item.raw_item, dict):
                            tool_name = item.raw_item.get("name") or item.raw_item.get("function", {}).get("name", "")
                        event_data["tool_name"] = str(tool_name)
                    elif item.type == "tool_call_output_item":
                         output = ""
                         if hasattr(item.raw_item, "output"):
                             output = item.raw_item.output
                         elif isinstance(item.raw_item, dict):
                             output = item.raw_item.get("output", "")
                         event_data["output"] = str(output)
                
                elif event.type == "agent_updated_stream_event":
                    event_data["new_agent"] = str(event.new_agent.name)
                
                yield f"data: {json.dumps(event_data, ensure_ascii=False, default=str)}\n\n"
            
        except Exception as e:
            logger.error(f"Error in streaming chat: {str(e)}")
            error_msg = json.dumps({"type": "error", "message": "服务内部错误"}, ensure_ascii=False)
            yield f"data: {error_msg}\n\n"
        finally:
            # 无论是否异常或中断，都保存会话状态到 Redis
            save_session(chat_request.session_id, session, user_id=user_id, app_type=chat_request.app_type)
            # 发送结束标记
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    print("准备启动应用后端 (开发模式 - 热重载已开启)")
    # 使用字符串路径以支持 reload=True
    # 在 Windows 下，reload 会开启子进程，需要确保 sys.path 在子进程中也被正确设置
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
