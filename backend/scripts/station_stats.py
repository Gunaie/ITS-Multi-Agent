"""
维修站数据库统计：查看导入进度（按城市分组计数）

用法:
    python backend/scripts/station_stats.py
"""
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _APP_DIR)
sys.path.insert(0, _BACKEND_DIR)
sys.path.insert(0, _HERE)  # 便于导入同目录的 import_lenovo_stations

from infrastructure.database.database_pool import pool
from import_lenovo_stations import CITIES


def main():
    conn = pool.connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM service_stations")
            total = cursor.fetchone()[0]
            print(f"库内网点总数: {total}")
            if total == 0:
                return

            cursor.execute("SELECT COALESCE(city, ''), address FROM service_stations")
            counter: Counter = Counter()
            for city, address in cursor.fetchall():
                if city:
                    counter[city] += 1
                else:
                    # 历史数据无 city 字段，按地址匹配已知城市名兜底
                    match = next((c for c in CITIES if c in (address or "")), None)
                    counter[match or "其他/无城市名"] += 1

            covered = len([k for k in counter if k not in ("其他/无城市名",)])
            print(f"已覆盖城市数: {covered}")
            print("-" * 30)
            for city, cnt in sorted(counter.items(), key=lambda x: -x[1]):
                print(f"  {city}: {cnt} 家")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
