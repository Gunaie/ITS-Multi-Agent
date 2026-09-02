"""
联想官方服务网点数据爬取入库脚本

数据源: 百度地图 Place API 区域检索（region + city_limit）
- 联想官方网点的真实命名高度统一（"联想客户服务中心"/"联想授权服务站"等），
  按城市检索这两类关键词可获得全国主要城市的官方网点全集。
- 坐标为百度 BD-09，与全链路坐标系一致。

可靠性设计（百度 AK 免费日配额很小，约百余次/天）:
1. 断点续传: 每完成一个城市即写入本地缓存文件（backend/scripts/.lenovo_stations_cache.json），
   再次运行自动跳过已完成城市。
2. 逐城入库: 正式模式下每城市抓完立即入库（幂等 ON DUPLICATE KEY），
   中断/配额耗尽不会浪费已抓数据。
3. 配额熔断: 遇到 status=302（天配额超限）立即停止并保存进度，
   第二天配额重置后重新运行同一命令即可继续。
4. dry-run 与正式模式共用缓存: dry-run 抓到的数据次日直接运行正式命令即可入库，无需重抓。

用法:
    python backend/scripts/import_lenovo_stations.py                  # 正式导入（自动断点续传）
    python backend/scripts/import_lenovo_stations.py --dry-run        # 仅抓取缓存不入库
    python backend/scripts/import_lenovo_stations.py --cities 武汉 北京  # 指定城市
    python backend/scripts/import_lenovo_stations.py --refresh        # 忽略断点重新抓取
    python backend/scripts/import_lenovo_stations.py --reset-cache    # 清空断点缓存
"""
import os
import sys
import json
import time
import hashlib
import argparse

# 路径设置: 使脚本能导入 backend/app 与 backend/common 下的模块
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _APP_DIR)
sys.path.insert(0, _BACKEND_DIR)

import httpx
import pymysql

from config.settings import settings
from common.infrastructure.logging.logger import logger
from infrastructure.database.init_db import init_db

CACHE_FILE = os.path.join(_HERE, ".lenovo_stations_cache.json")

# ---------------------------------------------------------------------------
# 城市列表（省会 + 主要地级市，可按需扩充）
# ---------------------------------------------------------------------------
CITIES = [
    # 直辖市
    "北京", "上海", "天津", "重庆",
    # 华北
    "石家庄", "唐山", "保定", "太原", "呼和浩特", "包头",
    # 东北
    "沈阳", "大连", "长春", "哈尔滨", "大庆",
    # 华东
    "南京", "苏州", "无锡", "常州", "南通", "徐州", "杭州", "宁波", "温州", "嘉兴", "金华",
    "合肥", "芜湖", "福州", "厦门", "泉州", "南昌", "赣州", "济南", "青岛", "烟台", "潍坊", "临沂",
    # 华中
    "郑州", "洛阳", "武汉", "宜昌", "襄阳", "长沙", "株洲", "岳阳", "衡阳",
    # 华南
    "广州", "深圳", "东莞", "佛山", "惠州", "中山", "珠海", "汕头", "南宁", "柳州", "桂林", "海口",
    # 西南
    "成都", "绵阳", "贵阳", "昆明", "拉萨",
    # 西北
    "西安", "咸阳", "宝鸡", "兰州", "西宁", "银川", "乌鲁木齐",
    # 其他重点
    "绍兴", "台州", "扬州", "泰州", "镇江",
]

# 每个城市检索的关键词（覆盖联想官方网点的真实命名）
QUERIES = ["联想客户服务中心", "联想授权服务站"]

REQUEST_INTERVAL_SEC = 0.4   # 控制 QPS（百度 AK 限制 3 QPS，0.4s 间隔 + 响应延迟稳妥不超限）
MAX_PAGES_PER_QUERY = 3      # 单关键词最多翻 3 页（20 条/页足够覆盖单城网点数）

QUOTA_ERROR_STATUS = 302     # 百度: 天配额超限，限制访问


class QuotaExhausted(Exception):
    """百度 AK 当日配额耗尽"""


class ApiError(Exception):
    """百度 Place API 调用失败（非配额类错误：IP 校验失败/参数错误等），跳过该城市且不标记 done"""


def _name_addr_hash(name: str, address: str) -> str:
    return hashlib.md5(f"{name.strip()}|{address.strip()}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 断点缓存
# ---------------------------------------------------------------------------
def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if isinstance(cache.get("done_cities"), list) and isinstance(cache.get("records"), dict):
                return cache
        except Exception as e:
            logger.warning(f"Cache file corrupted, starting fresh: {e}")
    return {"done_cities": [], "records": {}}


def save_cache(cache: dict) -> None:
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------
def search_city(client: httpx.Client, city: str, query: str, interval: float) -> list:
    """按城市+关键词做区域检索，自动翻页；配额超限抛出 QuotaExhausted"""
    all_results = []
    for page_num in range(MAX_PAGES_PER_QUERY):
        params = {
            "ak": settings.BAIDU_MAP_AK,
            "query": query,
            "region": city,
            "city_limit": "true",
            "output": "json",
            "scope": 2,
            "page_size": 20,
            "page_num": page_num,
        }
        try:
            resp = client.get("https://api.map.baidu.com/place/v2/search", params=params)
            data = resp.json()
        except Exception as e:
            logger.warning(f"[{city}] {query} request failed: {e}")
            raise ApiError(f"request failed: {e}")

        status = data.get("status")
        if status != 0:
            msg = data.get("message", "")
            if status == QUOTA_ERROR_STATUS or "配额" in str(msg):
                raise QuotaExhausted(f"[{city}] {query}: {msg}")
            logger.warning(f"[{city}] {query} API error: status={status}, msg={msg}")
            raise ApiError(f"status={status}, msg={msg}")

        results = data.get("results", [])
        all_results.extend(results)
        if len(results) < 20:
            break  # 最后一页
        time.sleep(interval)

    return all_results


def normalize_poi(poi: dict, city: str) -> dict | None:
    """原始 POI -> 入库记录（city 为抓取时的来源城市）"""
    name = (poi.get("name") or "").strip()
    address = (poi.get("address") or "").strip()
    location = poi.get("location") or {}
    lat, lng = location.get("lat"), location.get("lng")
    if not name or lat is None or lng is None:
        return None
    # 只保留联想相关网点，过滤同名异业的干扰结果
    if "联想" not in name and "lenovo" not in name.lower():
        return None
    # 过滤名称含"联想"但非维修网点的干扰项（如"联想家园"小区洗车店、"联想充电桩"）
    if any(k in name for k in ("洗车", "充电桩", "加油站", "驿站", "超市", "酒店")):
        return None
    return {
        "name": name,
        "address": address,
        "lat": float(lat),
        "lng": float(lng),
        "phone": _clean_phone(poi.get("telephone") or ""),
        "brand": "Lenovo",
        "city": city,
        "name_addr_hash": _name_addr_hash(name, address or name),
    }


def _clean_phone(raw: str) -> str:
    """清洗电话字段: 去括号、多电话取首个、400号补分隔。与 clean_db_phones.py 保持一致。"""
    if not raw:
        return ""
    import re
    parts = re.split(r'[,;；，/、\s]+', raw.strip())
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^\((\d{3,4})\)(\d+)$', part)
        if m:
            part = f"{m.group(1)}-{m.group(2)}"
        m4 = re.match(r'^(400)(\d{3})(\d{4})$', part)
        if m4:
            part = f"{m4.group(1)}-{m4.group(2)}-{m4.group(3)}"
        if re.match(r'^0\d{10,11}$', part) and '-' not in part:
            part = f"{part[:3]}-{part[3:]}"
        digits = re.sub(r'\D', '', part)
        if len(digits) >= 5:
            return part[:50]
    return ""


def _connect():
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset=settings.MYSQL_CHARSET,
    )


def save_to_db(records: list) -> int:
    """批量幂等入库，返回受影响行数"""
    if not records:
        return 0
    conn = _connect()
    try:
        affected = 0
        with conn.cursor() as cursor:
            for r in records:
                cursor.execute(
                    """INSERT INTO service_stations (name, address, lat, lng, phone, brand, city, name_addr_hash)
                       VALUES (%(name)s, %(address)s, %(lat)s, %(lng)s, %(phone)s, %(brand)s, %(city)s, %(name_addr_hash)s)
                       ON DUPLICATE KEY UPDATE
                           address = VALUES(address), lat = VALUES(lat), lng = VALUES(lng),
                           phone = VALUES(phone), city = VALUES(city)""",
                    r,
                )
                affected += cursor.rowcount
        conn.commit()
        return affected
    finally:
        conn.close()


def backfill_city_column(cache: dict) -> None:
    """为历史无 city 数据回填：优先用断点缓存的抓取来源，其次按地址匹配已知城市名（幂等）"""
    hash_to_city = {h: r["city"] for h, r in cache.get("records", {}).items() if r.get("city")}
    conn = _connect()
    try:
        fixed = 0
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name_addr_hash, address FROM service_stations WHERE city IS NULL")
            rows = cursor.fetchall()
            for row_id, na_hash, address in rows:
                city = hash_to_city.get(na_hash) or next(
                    (c for c in CITIES if c in (address or "")), None
                )
                if city:
                    cursor.execute("UPDATE service_stations SET city = %s WHERE id = %s", (city, row_id))
                    fixed += 1
        conn.commit()
        if fixed:
            print(f"为 {fixed} 条历史数据回填了 city 字段。")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="导入联想官方服务网点数据（断点续传）")
    parser.add_argument("--cities", nargs="*", default=None, help="指定城市（默认全量城市列表）")
    parser.add_argument("--dry-run", action="store_true", help="仅抓取并缓存，不入库")
    parser.add_argument("--refresh", action="store_true", help="忽略断点，重新抓取所有城市")
    parser.add_argument("--reset-cache", action="store_true", help="清空断点缓存后运行")
    parser.add_argument("--interval", type=float, default=REQUEST_INTERVAL_SEC, help="请求间隔秒数")
    args = parser.parse_args()

    if not settings.BAIDU_MAP_AK:
        print("❌ 未配置 BAIDU_MAP_AK，无法执行爬取。请在 .env 中配置后重试。")
        sys.exit(1)

    # 确保表结构与唯一索引就绪（幂等，避免写入时 Unknown column）
    init_db()

    if args.reset_cache and os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
        print("已清空断点缓存。")

    cache = load_cache()
    done_cities: list = cache["done_cities"]
    records: dict = cache["records"]

    # 为历史无 city 的数据回填来源城市（幂等）
    backfill_city_column(cache)

    cities = args.cities or CITIES
    seen = set()
    cities = [c for c in cities if not (c in seen or seen.add(c))]

    # 正式模式下，先把缓存中已有的历史记录入库（覆盖 dry-run 先行抓取的场景，幂等）
    if not args.dry_run and records:
        affected = save_to_db(list(records.values()))
        print(f"断点缓存中已有 {len(records)} 条记录，先行入库（影响 {affected} 行）。")

    mode = "dry-run" if args.dry_run else "正式"
    pending = [c for c in cities if args.refresh or c not in done_cities]
    skipped = len(cities) - len(pending)
    print(f"模式: {mode} | 城市: {len(cities)} 个 (断点跳过 {skipped} 个，待抓取 {len(pending)} 个) × {len(QUERIES)} 组关键词")

    client = httpx.Client(timeout=10.0)
    total_new = 0
    try:
        for i, city in enumerate(pending, 1):
            city_pois = []
            api_failed = False
            try:
                for query in QUERIES:
                    city_pois.extend(search_city(client, city, query, args.interval))
                    time.sleep(args.interval)
            except QuotaExhausted as e:
                # 配额熔断: 保存进度后立即退出，明日重跑自动续传
                save_cache(cache)
                print(f"\n⛔ 百度 AK 当日配额已耗尽: {e}")
                print(f"   已完成 {len(done_cities)}/{len(cities)} 个城市，进度已保存。")
                print("   明天配额重置后重新运行同一命令即可从断点继续。")
                sys.exit(2)
            except ApiError as e:
                # API 错误(IP 白名单/参数/网络): 跳过本轮城市，不标记 done，下次重跑自动重试
                api_failed = True
                print(f"[{i}/{len(pending)}] {city}: ⚠️ API错误，跳过不标记完成({e})，下次重跑自动重试")
                continue

            if not api_failed:
                new_records = []
                for poi in city_pois:
                    rec = normalize_poi(poi, city)
                    if rec and rec["name_addr_hash"] not in records:
                        records[rec["name_addr_hash"]] = rec
                        new_records.append(rec)
                total_new += len(new_records)

                # 断点保存 + 正式模式逐城立即入库（中断/配额耗尽不丢数据）
                done_cities.append(city)
                save_cache(cache)
                if not args.dry_run and new_records:
                    save_to_db(new_records)

                print(f"[{i}/{len(pending)}] {city}: +{len(new_records)} 条新网点 (累计 {len(records)})")
    finally:
        client.close()

    # 正式模式兜底: 将缓存全量幂等入库一次（确保 dry-run 转正式/中断恢复的数据全部落库）
    if not args.dry_run and records:
        affected = save_to_db(list(records.values()))
        print(f"\n入库完成: 缓存 {len(records)} 条全量幂等入库（影响 {affected} 行）。")
    else:
        print(f"\n抓取完成: 累计 {len(records)} 条记录（dry-run 未写库）。")
        print("次日配额重置后运行正式命令即可入库并继续抓取剩余城市。")


if __name__ == "__main__":
    main()
