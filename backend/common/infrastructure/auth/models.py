import sys
import os
# 向上三级到达 backend 目录
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.infrastructure.database.database_pool import DatabasePool
from ..logging.logger import logger
from typing import Optional, Dict, Any
import pymysql.cursors

class UserRepo:
    @staticmethod
    def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
        conn = DatabasePool.get_connection()
        try:
            with conn.cursor(cursor=pymysql.cursors.DictCursor) as cursor:
                sql = "SELECT id, username, hashed_password FROM users WHERE username = %s"
                cursor.execute(sql, (username,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting user by username: {e}")
            return None
        finally:
            conn.close()

    @staticmethod
    def create_user(username: str, hashed_password: str) -> bool:
        conn = DatabasePool.get_connection()
        try:
            with conn.cursor() as cursor:
                sql = "INSERT INTO users (username, hashed_password) VALUES (%s, %s)"
                cursor.execute(sql, (username, hashed_password))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    @staticmethod
    def init_table():
        try:
            conn = DatabasePool.get_connection()
            try:
                with conn.cursor() as cursor:
                    sql = """
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(50) NOT NULL UNIQUE,
                        hashed_password VARCHAR(255) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                    cursor.execute(sql)
                    conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Error initializing users table: {e}")
            # 如果是数据库不存在，尝试在 main.py 或 init_db.py 中解决，这里只记录
