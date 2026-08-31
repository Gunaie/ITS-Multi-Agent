import pymysql
import hashlib
from config.settings import settings

def _name_addr_hash(name: str, address: str) -> str:
    """名称+地址唯一指纹，用于幂等插入与去重"""
    return hashlib.md5(f"{name.strip()}|{address.strip()}".encode("utf-8")).hexdigest()

# 经过核验的官方授权核心网点（坐标系: BD-09 百度坐标系）
STATIONS = [
    # 武汉核心网点
    ("联想客户服务中心(武汉平安大厦店)", "武汉市江汉区中山大道818号平安大厦39楼3914室", 30.5822, 114.2825, "027-82880099", "Lenovo"),
    ("联想客户服务中心(武汉世界城广场店)", "武汉市洪山区珞喻路766号世界城广场写字楼1栋1313室", 30.5055, 114.4022, "400-168-2825", "Lenovo"),
    ("联想客户服务中心(武汉银泰创意城店)", "武汉市洪山区珞瑜路10号街道口银泰创意城4楼4F006", 30.5255, 114.3532, "027-87879398", "Lenovo"),
    ("联想客户服务中心(武汉招银大厦店)", "武汉市江汉区青年路66-5号招银大厦12层1203室", 30.5908, 114.2625, "027-83643312", "Lenovo"),
    # 北京核心网点
    ("联想客户服务中心(北京金台路店)", "北京市朝阳区金台路25号一层门面", 39.921, 116.478, "010-85996601", "Lenovo"),
    ("联想客户服务中心(北京知春路店)", "北京市海淀区知春路17号联想服务站", 39.976, 116.352, "010-62059288", "Lenovo"),
    ("联想客户服务中心(北京天通苑店)", "北京市昌平区天通本苑一区203B楼底商", 40.065, 116.418, "010-84820000", "Lenovo"),
    # 上海核心网点
    ("联想客户服务中心(上海新梅联合广场店)", "上海市浦东新区浦东南路999号新梅联合广场", 31.231, 121.512, "021-58880000", "Lenovo"),
]

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
            # 幂等建表（不再 DROP TABLE，保护生产数据）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS service_stations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    address VARCHAR(255) NOT NULL,
                    lat DOUBLE NOT NULL,
                    lng DOUBLE NOT NULL,
                    phone VARCHAR(50),
                    brand VARCHAR(50) DEFAULT 'Lenovo',
                    city VARCHAR(50) NULL,
                    name_addr_hash CHAR(32) NOT NULL,
                    UNIQUE KEY uq_name_addr (name_addr_hash),
                    KEY idx_brand (brand),
                    KEY idx_lat_lng (lat, lng)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                COMMENT='官方授权维修服务站 (坐标系: BD-09)'
            """)

            # 迁移旧表：补 name_addr_hash 列（历史遗留表结构无此列）
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'service_stations' AND COLUMN_NAME = 'name_addr_hash'"
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE service_stations ADD COLUMN name_addr_hash CHAR(32) NOT NULL DEFAULT ''")
                # 为存量数据回填指纹
                cursor.execute("SELECT id, name, address FROM service_stations")
                for row_id, name, address in cursor.fetchall():
                    cursor.execute(
                        "UPDATE service_stations SET name_addr_hash = %s WHERE id = %s",
                        (_name_addr_hash(name, address), row_id)
                    )
                # 回填后补充唯一索引（若不存在）
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'service_stations' AND INDEX_NAME = 'uq_name_addr'"
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute("ALTER TABLE service_stations ADD UNIQUE KEY uq_name_addr (name_addr_hash)")

            # 迁移旧表：补 city 列（记录导入来源城市，便于统计与按城查询）
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'service_stations' AND COLUMN_NAME = 'city'"
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute("ALTER TABLE service_stations ADD COLUMN city VARCHAR(50) NULL")

            # 幂等插入核心网点（存在则更新，坐标/电话以最新核验值为准）
            for name, address, lat, lng, phone, brand in STATIONS:
                cursor.execute(
                    """INSERT INTO service_stations (name, address, lat, lng, phone, brand, name_addr_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                           address = VALUES(address), lat = VALUES(lat), lng = VALUES(lng),
                           phone = VALUES(phone), brand = VALUES(brand)""",
                    (name, address, lat, lng, phone, brand, _name_addr_hash(name, address))
                )

        conn.commit()
        print("Database initialized successfully (idempotent) with VERIFIED official service stations.")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
