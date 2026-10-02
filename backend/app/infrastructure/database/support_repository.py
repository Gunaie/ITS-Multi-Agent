"""
人工工单 / 消息反馈 — 数据访问层

support_tickets   : 转人工 / 投诉 / 在线未解决问题的人工跟进工单
message_feedback  : 助手消息点赞/点踩（同一会话同一轮次每用户唯一，重复提交即更新）
"""
from typing import Optional, Dict, Any, List

import pymysql
import pymysql.cursors

from infrastructure.database.database_pool import DatabasePool
from common.infrastructure.logging.logger import logger


# 允许的状态/评分取值（接口层兜底校验）
TICKET_STATUS = {"open", "processing", "closed", "cancelled"}
FEEDBACK_RATING = {"up", "down"}


class TicketRepo:
    """人工工单"""

    @staticmethod
    def create(user_id: int, username: str, session_id: str,
               category: str, content: str, contact: str = "") -> int:
        conn = DatabasePool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO support_tickets
                       (user_id, username, session_id, category, content, contact)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (user_id, username, session_id,
                     category or "技术问题", content, contact)
                )
                conn.commit()
                return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def list_by_user(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        conn = DatabasePool.get_connection()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """SELECT id, user_id, username, session_id, category, content,
                              contact, status, created_at, updated_at
                       FROM support_tickets WHERE user_id = %s
                       ORDER BY id DESC LIMIT %s""",
                    (user_id, min(int(limit), 200))
                )
                return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_for_user(ticket_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        conn = DatabasePool.get_connection()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """SELECT id, user_id, username, session_id, category, content,
                              contact, status, created_at, updated_at
                       FROM support_tickets WHERE id = %s AND user_id = %s""",
                    (ticket_id, user_id)
                )
                return cursor.fetchone()
        finally:
            conn.close()

    @staticmethod
    def update_status(ticket_id: int, user_id: int, status: str) -> int:
        """更新本人工单状态，返回受影响行数（0 = 工单不存在或无变化）。"""
        if status not in TICKET_STATUS:
            raise ValueError(f"invalid ticket status: {status}")
        conn = DatabasePool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE support_tickets SET status = %s WHERE id = %s AND user_id = %s",
                    (status, ticket_id, user_id)
                )
                conn.commit()
                return cursor.rowcount
        finally:
            conn.close()


class FeedbackRepo:
    """消息赞/踩"""

    @staticmethod
    def upsert(user_id: int, username: str, session_id: str, turn_index: int,
               rating: str, reason: str = "", comment: str = "") -> Dict[str, Any]:
        """
        按 (user_id, session_id, turn_index) 幂等写入：
        首次 -> INSERT，再次提交 -> UPDATE 评分/原因/备注。
        返回 {"id": ..., "action": "created"|"updated"}。
        """
        if rating not in FEEDBACK_RATING:
            raise ValueError(f"invalid rating: {rating}")
        turn_index = int(turn_index)

        conn = DatabasePool.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM message_feedback "
                    "WHERE user_id = %s AND session_id = %s AND turn_index = %s",
                    (user_id, session_id, turn_index)
                )
                row = cursor.fetchone()
                if row:
                    feedback_id = row[0]
                    cursor.execute(
                        """UPDATE message_feedback
                           SET rating = %s, reason = %s, comment = %s
                           WHERE id = %s""",
                        (rating, reason, comment, feedback_id)
                    )
                    action = "updated"
                else:
                    cursor.execute(
                        """INSERT INTO message_feedback
                           (user_id, username, session_id, turn_index, rating, reason, comment)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (user_id, username, session_id, turn_index,
                         rating, reason, comment)
                    )
                    feedback_id = cursor.lastrowid
                    action = "created"
                conn.commit()
                return {"id": feedback_id, "action": action}
        finally:
            conn.close()

    @staticmethod
    def list_by_user(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        conn = DatabasePool.get_connection()
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """SELECT id, session_id, turn_index, rating, reason, comment,
                              created_at, updated_at
                       FROM message_feedback WHERE user_id = %s
                       ORDER BY id DESC LIMIT %s""",
                    (user_id, min(int(limit), 200))
                )
                return cursor.fetchall()
        finally:
            conn.close()
