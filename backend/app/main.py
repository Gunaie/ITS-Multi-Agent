import os
import sys
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import json
import asyncio
from agents import Runner, RunConfig
from infrastructure.logging.logger import logger
from multi_agent.orchestrator import orchestrator_agent
from infrastructure.auth.router import router as auth_router
from infrastructure.auth.models import UserRepo
from infrastructure.auth.deps import get_current_user
from infrastructure.limiter import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# 将当前目录添加到 Python 路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 强制设置 sys.stdout 编码为 utf-8 以防止 Windows 下的 UnicodeEncodeError
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

app = FastAPI(title="ITS Multi-Agent Application Backend")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "智能体系统繁忙，请稍后再试。"},
    )

# 注册 Auth 路由
app.include_router(auth_router)

from infrastructure.tools.mcp.mcp_servers import search_mac_client, amap_map_mcp
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
        try:
            await search_mac_client.connect()
            technical_agent.mcp_servers = [search_mac_client]
            logger.info("Connected to MCP Search service.")
        except Exception as e:
            logger.warning(f"Failed to connect to MCP Search service: {e}")
            
        try:
            await amap_map_mcp.connect()
            comprehensive_service_agent.mcp_servers = [amap_map_mcp]
            logger.info("Connected to MCP Map service.")
        except Exception as e:
            logger.warning(f"Failed to connect to MCP Map service: {e}")
            
    asyncio.create_task(init_mcp())

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"
    location: str = None

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

def save_session(session_id: str, session: Session, user_id: str = None):
    try:
        # 保存会话内容 (使用 pickle 以支持 agents 库的复杂对象)
        binary_redis_client.setex(
            f"session:{session_id}",
            60 * 60 * 24 * 7,  # 延长至7天
            pickle.dumps(session)
        )
        # 如果提供了用户ID，维护用户的会话列表
        if user_id:
            # 使用有序集合存储，以时间戳排序
            redis_client.zadd(f"user_sessions:{user_id}", {session_id: time.time()})
            # 记录会话的元数据（如标题）
            if not redis_client.exists(f"session_meta:{session_id}"):
                # 初始标题使用第一条提问的前10个字
                title = "新对话"
                if hasattr(session, 'items') and len(session.items) > 0:
                    first_msg = session.items[0]
                    # 处理 dict 或 ResponseInputItemParam 对象
                    content = ""
                    if isinstance(first_msg, dict):
                        content = first_msg.get("content", "")
                    elif hasattr(first_msg, "content"):
                         if isinstance(first_msg.content, list):
                             for part in first_msg.content:
                                 if hasattr(part, "text"): content += part.text
                         elif isinstance(first_msg.content, str):
                             content = first_msg.content
                    
                    if content:
                        title = content[:15] + ("..." if len(content) > 15 else "")
                
                redis_client.hset(f"session_meta:{session_id}", mapping={
                    "title": title,
                    "created_at": time.time()
                })
    except Exception as e:
        logger.error(f"Error saving session to redis: {e}")

@app.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    user_id = current_user['username'] # 使用用户名作为标识
    session_ids = redis_client.zrevrange(f"user_sessions:{user_id}", 0, -1)
    
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
            content = ""
            
            if role == "user":
                content = item.get("content")
            elif role == "assistant":
                content = item.get("content")
                # 处理可能的 tool_calls 等（这里简化为只取文本）
            
            if content and isinstance(content, str):
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
        # 保存会话状态到 Redis，传入 user_id 以便列出
        save_session(chat_request.session_id, session, user_id=user_id)

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
        save_session(chat_request.session_id, session, user_id=user_id)
        
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
        try:
            user_id = current_user['username']
            logger.info(f"User {user_id} asked (stream): {chat_request.question}")
            session = get_session(chat_request.session_id)
            
            # 手动添加用户消息到 Session 以便持久化历史
            await session.add_items([{"role": "user", "content": chat_request.question}])
            
            if chat_request.location:
                session.context["user_location"] = chat_request.location
            
            # 使用 run_streamed 启动流式运行，传入 session 和 context
            stream = Runner.run_streamed(
                orchestrator_agent, 
                input=chat_request.question, 
                session=session,
                context=session,
                run_config=RunConfig(tracing_disabled=False)
            )
            
            async for event in stream.stream_events():
                # 根据事件类型封装成 SSE 格式
                # 过滤掉一些过于琐碎的原始响应事件，只发送关键的 run_item_stream_event 和 agent_updated_stream_event
                
                event_data = {
                    "type": str(event.type),
                }
                
                if event.type == "run_item_stream_event":
                    event_data["name"] = str(event.name)
                    item = event.item
                    event_data["item_type"] = str(item.type)
                    
                    if item.type == "message_output_item":
                        # 消息内容输出
                        content = ""
                        reasoning_content = ""
                        raw = item.raw_item
                        
                        # 统一文本提取逻辑
                        def extract_text(obj):
                            if not obj: return ""
                            if isinstance(obj, str): return obj
                            if isinstance(obj, list): return "".join([extract_text(i) for i in obj])
                            
                            # 优先尝试 content 属性或字段
                            content = getattr(obj, "content", None) or (obj.get("content") if isinstance(obj, dict) else None)
                            if content:
                                if content is obj: return str(obj) # 防止递归
                                return extract_text(content)
                                
                            # 备选：text 属性或字段
                            text = getattr(obj, "text", None) or (obj.get("text") if isinstance(obj, dict) else None)
                            if text: return str(text)
                            
                            return str(obj)

                        if hasattr(raw, "content") and raw.content:
                            content = extract_text(raw.content)
                        elif hasattr(raw, "choices") and len(raw.choices) > 0:
                             delta = raw.choices[0].delta
                             content = extract_text(getattr(delta, "content", ""))
                             reasoning_content = extract_text(getattr(delta, "reasoning_content", ""))
                        
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
                
                # 发送 SSE 数据包，使用 default=str 确保所有不可序列化对象转为字符串
                yield f"data: {json.dumps(event_data, ensure_ascii=False, default=str)}\n\n"
            
            # 保存会话状态到 Redis
            save_session(chat_request.session_id, session, user_id=user_id)

            # 发送结束标记
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"Error in streaming chat: {str(e)}")
            error_msg = json.dumps({"type": "error", "message": "服务内部错误"}, ensure_ascii=False)
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
