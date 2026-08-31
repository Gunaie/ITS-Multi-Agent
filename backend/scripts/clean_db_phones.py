"""一次性清洗 DB 存量电话字段。

修复历史脏数据:
- (027)87819387 -> 027-87819387
- 15377676079,18107108004 -> 15377676079 (取首个有效号码)
- 4001050717 (无分隔) -> 400-105-0717 (400 号段补分隔，提升可读性与匹配稳定性)
"""
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "app")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))

import re
import pymysql
from config.settings import settings


def clean_phone(raw: str) -> str:
    """清洗单个电话字段 -> 标准格式（首个有效号码）。"""
    if not raw or not raw.strip():
        return ""
    # 按常见分隔符拆分，取首个有效号码
    parts = re.split(r'[,;；，/、\s]+', raw.strip())
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 去括号: (027)87819387 -> 027-87819387
        m = re.match(r'^\((\d{3,4})\)(\d+)$', part)
        if m:
            part = f"{m.group(1)}-{m.group(2)}"
        # 400 号段无分隔: 4001050717 -> 400-105-0717
        m4 = re.match(r'^(400)(\d{3})(\d{4})$', part)
        if m4:
            part = f"{m4.group(1)}-{m4.group(2)}-{m4.group(3)}"
        # 纯数字座机无分隔且以0开头（02787819387）-> 027-87819387
        if re.match(r'^0\d{10,11}$', part) and '-' not in part:
            part = f"{part[:3]}-{part[3:]}"
        # 验证: 至少5位数字才保留
        digits = re.sub(r'\D', '', part)
        if len(digits) >= 5:
            return part
    return ""


def main():
    conn = pymysql.connect(
        host=settings.MYSQL_HOST, port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER, password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE, charset=settings.MYSQL_CHARSET,
    )
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT id, phone FROM service_stations")
            rows = cur.fetchall()
            print(f"待清洗记录: {len(rows)} 条")
            updated = 0
            for r in rows:
                cleaned = clean_phone(r['phone'] or '')
                if cleaned != (r['phone'] or ''):
                    cur.execute("UPDATE service_stations SET phone=%s WHERE id=%s", (cleaned, r['id']))
                    updated += 1
                    print(f"  [{r['id']}] {r['phone']!r} -> {cleaned!r}")
            conn.commit()
            print(f"\n清洗完成: {updated} 条更新（共 {len(rows)} 条）")

            # 复查
            cur.execute("SELECT COUNT(*) c FROM service_stations WHERE phone IS NULL OR phone = ''")
            print(f"清洗后空电话数: {cur.fetchone()['c']}")
            cur.execute("SELECT phone FROM service_stations WHERE phone LIKE '%,%' OR phone LIKE '%(%' LIMIT 5")
            bad = cur.fetchall()
            print(f"清洗后仍含括号/逗号的: {len(bad)} 条")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
