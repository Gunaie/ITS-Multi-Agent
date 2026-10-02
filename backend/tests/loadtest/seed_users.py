"""
压测预置账号脚本 — 直接写入 MySQL（绕开注册接口 5/min 的 HTTP 限流）

默认写入压测共享账号 load_shared / Load1234!。
Locust 压测时所有虚拟用户共享该账号的 JWT，避免登录 10/min 限流
导致大规模用户无法在启动窗口内完成认证。

用法（app venv）：
  .\\backend\\app\\.venv\\Scripts\\python.exe backend\\tests\\loadtest\\seed_users.py
"""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "app")))

import pymysql
from config.settings import settings
from common.infrastructure.auth.security import get_password_hash

# 压测共享账号（与 locustfile.py 中保持一致）
SHARED_USERNAME = "load_shared"
SHARED_PASSWORD = "Load1234!"


def seed() -> None:
    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset=settings.MYSQL_CHARSET,
    )
    try:
        with conn.cursor() as cursor:
            # 确保 users 表存在（正常情况下启动 lifespan 的 init_db 不建 users，
            # users 表由 UserRepo 惰性创建；此处兜底）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    hashed_password VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(
                "INSERT INTO users (username, hashed_password) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE hashed_password = VALUES(hashed_password)",
                (SHARED_USERNAME, get_password_hash(SHARED_PASSWORD)),
            )
        conn.commit()
        print(f"压测账号已就绪：{SHARED_USERNAME}")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
