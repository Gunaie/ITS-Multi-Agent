import pymysql
from config.settings import settings

def init_db():
    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset=settings.MYSQL_CHARSET
    )
    try:
        with conn.cursor() as cursor:
            # 创建服务站表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS service_stations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    address VARCHAR(255) NOT NULL,
                    lat DOUBLE NOT NULL,
                    lng DOUBLE NOT NULL,
                    phone VARCHAR(50),
                    type VARCHAR(50)
                )
            """)
            
            # 插入一些模拟数据
            stations = [
                ("联想服务中心 (昌平店)", "北京市昌平区回龙观西大街", 40.078, 116.345, "010-12345678", "Lenovo"),
                ("小米之家 (海淀店)", "北京市海淀区清河中街", 40.033, 116.341, "010-87654321", "Xiaomi"),
                ("华为授权服务中心 (朝阳店)", "北京市朝阳区建国门外大街", 39.908, 116.453, "010-11223344", "Huawei"),
                ("苹果授权维修点 (三里屯)", "北京市朝阳区三里屯路", 39.933, 116.455, "010-55667788", "Apple")
            ]
            
            cursor.execute("DELETE FROM service_stations")
            cursor.executemany(
                "INSERT INTO service_stations (name, address, lat, lng, phone, type) VALUES (%s, %s, %s, %s, %s, %s)",
                stations
            )
            
        conn.commit()
        print("Database initialized successfully with mock service stations.")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
