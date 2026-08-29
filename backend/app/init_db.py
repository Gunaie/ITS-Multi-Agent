import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("MYSQL_HOST", "localhost")
port = int(os.getenv("MYSQL_PORT", 3306))
user = os.getenv("MYSQL_USER", "root")
password = os.getenv("MYSQL_PASSWORD", "12345678")
database = os.getenv("MYSQL_DATABASE", "its")

try:
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password
    )
    with conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        print(f"Database '{database}' created or already exists.")
    conn.commit()
    conn.close()
except Exception as e:
    print(f"Error creating database: {e}")
