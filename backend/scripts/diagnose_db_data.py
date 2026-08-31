"""一次性诊断 DB 数据质量：电话格式分布、坐标精度、与百度 POI 的差异。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymysql
from config.settings import settings

def main():
    conn = pymysql.connect(
        host=settings.MYSQL_HOST, port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER, password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE, charset=settings.MYSQL_CHARSET,
    )
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 1. 总览
            cur.execute("SELECT COUNT(*) c FROM service_stations")
            print(f"DB 总网点数: {cur.fetchone()['c']}")

            # 2. 电话格式分布
            cur.execute("""
                SELECT phone,
                       CASE
                         WHEN phone IS NULL OR phone = '' THEN '空'
                         WHEN phone LIKE '400%' OR phone LIKE '400-%' THEN '400号'
                         WHEN phone LIKE '0%-%' THEN '座机带分隔'
                         WHEN phone LIKE '0%' THEN '座机无分隔'
                         WHEN phone REGEXP '^[0-9]+$' THEN '纯数字'
                         ELSE '其他'
                       END AS fmt
                FROM service_stations WHERE city = '武汉'
            """)
            rows = cur.fetchall()
            print(f"\n武汉门店数: {len(rows)}")
            from collections import Counter
            fmt_dist = Counter(r['fmt'] for r in rows)
            print(f"电话格式分布: {dict(fmt_dist)}")
            print("\n武汉门店电话样本（前15条）:")
            for i, r in enumerate(rows[:15]):
                print(f"  [{i+1}] fmt={r['fmt']:<8} phone={r['phone']!r}")

            # 3. 坐标精度
            cur.execute("""
                SELECT name, lat, lng, LENGTH(CAST(lat AS CHAR)) lat_len,
                       LENGTH(CAST(lng AS CHAR)) lng_len
                FROM service_stations WHERE city = '武汉' LIMIT 10
            """)
            print("\n武汉门店坐标精度样本:")
            for r in cur.fetchall():
                print(f"  {r['name'][:20]:<22} lat={r['lat']} lng={r['lng']} (lat_len={r['lat_len']}, lng_len={r['lng_len']})")

            # 4. 空电话数量
            cur.execute("SELECT COUNT(*) c FROM service_stations WHERE phone IS NULL OR phone = ''")
            print(f"\n空电话网点数: {cur.fetchone()['c']}")

            # 5. 重复坐标检测（坐标完全相同的可能是抓取错误）
            cur.execute("""
                SELECT lat, lng, COUNT(*) cnt, GROUP_CONCAT(name SEPARATOR ' | ') names
                FROM service_stations GROUP BY lat, lng HAVING cnt > 1 LIMIT 5
            """)
            dups = cur.fetchall()
            print(f"坐标完全重复的组数: {len(dups)}")
            for r in dups:
                print(f"  ({r['lat']},{r['lng']}) x{r['cnt']}: {r['names'][:60]}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
