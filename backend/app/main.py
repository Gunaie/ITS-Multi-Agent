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
from agents import Runner, RunConfig
from common.infrastructure.logging.logger import logger
from multi_agent.orchestrator import orchestrator_agent
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

from infrastructure.tools.mcp.mcp_servers import search_mac_client
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
        
        for i in range(3):
            try:
                # 增加 8 秒硬超时，防止连接挂起
                async def connect_safe(client, name):
                    try:
                        await asyncio.wait_for(client.connect(), timeout=5.0)
                        logger.info(f"Successfully connected to MCP {name} service.")
                        return True
                    except Exception as e:
                        # 尝试解包 ExceptionGroup 以获取底层错误
                        error_detail = str(e)
                        if hasattr(e, 'exceptions'):
                            error_detail = "; ".join([str(ex) for ex in e.exceptions])
                        logger.warning(f"MCP {name} connection failed: {error_detail}")
                        return False

                # 仅并行执行搜索连接任务
                results = await asyncio.gather(
                    connect_safe(search_mac_client, "Search"),
                    return_exceptions=True
                )
                
                search_ok = results[0] if isinstance(results[0], bool) else False
                
                if search_ok:
                    technical_agent.mcp_servers = [search_mac_client]
                
                if search_ok:
                    logger.info("MCP services are ready.")
                    break
            except Exception as e:
                logger.error(f"MCP connection iteration {i+1} encountered unexpected error: {e}")
            
            await asyncio.sleep(2)
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
        
        if chat_request.location:
            session.context["user_location"] = chat_request.location
            
        # 运行编排智能体，传入 session 和 context
        logger.info("Starting Agent Runner...")
        result = await Runner.run(
            orchestrator_agent, 
            input=chat_request.question, 
            session=session,
            context=session,
            run_config=RunConfig(tracing_disabled=not (settings.LANGCHAIN_TRACING_V2.lower() == "true"))
        )
        logger.info("Agent Runner finished successfully")
        
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
            
            if chat_request.location:
                session.context["user_location"] = chat_request.location
            
            # 使用 run_streamed 启动流式运行，传入 session 和 context
            stream = Runner.run_streamed(
                orchestrator_agent, 
                input=chat_request.question, 
                session=session,
                context=session,
                run_config=RunConfig(tracing_disabled=not (settings.LANGCHAIN_TRACING_V2.lower() == "true"))
            )
            
            full_reasoning = ""
            # 为了在 SSE 中优雅处理超时，我们使用 asyncio.timeout 包装整个生成逻辑
            try:
                async with asyncio.timeout(60.0):
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
                logger.error("Streaming chat timed out after 60s")
                yield f"data: {json.dumps({'type': 'error', 'message': '响应超时，请尝试提供更具体的地点或稍后重试。'}, ensure_ascii=False)}\n\n"
            
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
