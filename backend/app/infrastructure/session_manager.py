"""会话持久化管理: Redis 读写 Agent 会话、用户会话列表、会话元数据(标题等)。

序列化选型: agents SDK 的 Session 对象内含 Agent 实例、工具调用记录、运行时状态等
复杂结构, JSON 无法直接序列化, 采用 pickle 二进制序列化。
安全权衡: pickle.loads 理论上存在反序列化漏洞风险, 但本项目 Redis 仅绑定 127.0.0.1
本机访问, 不对外暴露, 且 session key 由后端生成(非用户可控), 实际攻击面极小。
生产环境强化建议: ① 给 pickle 数据加 HMAC 签名校验; ② 或实现 Session 的
自定义 JSON 编码器(仅提取 items/context 等必要字段)。
"""
import pickle
import time
import logging

from infrastructure.database.redis_client import binary_redis_client, redis_client
from infrastructure.database.session_impl import SimpleSession
from infrastructure.text_utils import extract_text, clean_history_text

logger = logging.getLogger(__name__)


def get_session(session_id: str):
    """从 Redis 加载会话, 不存在或加载失败时返回新会话。"""
    session_data = binary_redis_client.get(f"session:{session_id}")
    if session_data:
        try:
            return pickle.loads(session_data)
        except Exception as e:
            logger.error(f"Error loading session from redis: {e}")

    # 如果不存在或加载失败，创建新会话
    new_session = SimpleSession(session_id=session_id)
    return new_session


def save_session(session_id: str, session, user_id: str = None, app_type: str = "agent"):
    """保存会话到 Redis(pickle 序列化, 7 天 TTL), 并维护用户会话列表与元数据。

    首次保存时自动从第一条用户消息提取标题(前 15 字)。
    """
    try:
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
                    content = clean_history_text(content)  # 标题同样剔除注入片段
                    if content:
                        title = content[:15] + ("..." if len(content) > 15 else "")

                redis_client.hset(f"session_meta:{session_id}", mapping={
                    "title": title,
                    "created_at": time.time(),
                    "app_type": app_type
                })
    except Exception as e:
        logger.error(f"Error saving session to redis: {e}")
