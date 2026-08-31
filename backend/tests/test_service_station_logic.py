"""
业务服务专家 - 纯逻辑单元测试（无外部服务依赖）

覆盖: 电话归一化匹配 / 名称相似度 / 地址结构比对 / 坐标转换 /
     前端定位解析 / 定位TTL / haversine / IP过滤 / 多关键词去重

运行:
    python backend/tests/test_service_station_logic.py
"""
import os
import sys
import time
import asyncio

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _APP_DIR)
sys.path.insert(0, _BACKEND_DIR)

PASS = 0
FAIL = 0

def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")

# ---------------------------------------------------------------------------
print("\n[1] 电话归一化匹配 phone_match")
from infrastructure.tools.local.service_station import (
    phone_match, normalize_phone, normalize_name, name_ratio,
    addr_jaccard, haversine, merge_and_dedup, verify_official_stations,
)

check("格式差异: 400-168-2825 vs 4001682825", phone_match("400-168-2825", "4001682825"))
check("国际区号: +86 027-82880099 vs 02782880099", phone_match("+86 027-82880099", "02782880099"))
check("分机互含: 027-82880099-101 vs 02782880099", phone_match("027-82880099-101", "02782880099"))
check("尾8位一致: 01085996601 vs 85996601", phone_match("01085996601", "85996601"))
check("不同号码不匹配: 13800138000 vs 13900139000", not phone_match("13800138000", "13900139000"))
check("过短号码不匹配: 123 vs 1234", not phone_match("123", "1234"))
check("空号码不匹配", not phone_match("", "02782880099"))
# 多电话字段拆分匹配（百度 POI 常返回逗号分隔的多号码）
check("多电话字段: '15377676079,18107108004' vs '15377676079'", phone_match("15377676079,18107108004", "15377676079"))
check("多电话双向: '02782880099' vs '02782880099;13800138000'", phone_match("02782880099", "02782880099;13800138000"))
check("多电话均不匹配: '15377676079,18107108004' vs '02782880099'", not phone_match("15377676079,18107108004", "02782880099"))

print("\n[2] 名称相似度 name_ratio")
check("同店去后缀: 联想客户服务中心(武汉平安大厦店) vs 联想客户服务中心",
      name_ratio("联想客户服务中心(武汉平安大厦店)", "联想客户服务中心") == 1.0)
check("空白归一", normalize_name("联想 客户服务中心") == "联想客户服务中心")
r = name_ratio("武汉联想维修中心", "联想客户服务中心")
check(f"不同业态名称低于1 (实际 {r:.2f})", r < 1.0)

print("\n[3] 地址结构比对 addr_jaccard")
aj_same = addr_jaccard("武汉市江汉区中山大道818号平安大厦39楼", "江汉区中山大道818号平安大厦39楼3914室")
check(f"同址相似 (实际 {aj_same:.2f})", aj_same >= 0.4)
aj_diff = addr_jaccard("中山大道818号", "中山大道100号")
check(f"同路不同门牌不误判 (实际 {aj_diff:.2f})", aj_diff < 0.4)

print("\n[4] haversine 直线距离")
wh2bj = haversine(30.5928, 114.3055, 39.9042, 116.4074)
check(f"武汉->北京约1053km (实际 {wh2bj:.0f}km)", 1020 <= wh2bj <= 1090)
check("同点为0", haversine(30.5, 114.3, 30.5, 114.3) < 1e-6)

print("\n[5] 前端定位解析 parse_frontend_location")
from infrastructure.tools.local.location_service import (
    parse_frontend_location, ResolvedLocation, LocationSource, is_public_ip,
    wgs84_to_bd09,
)
check("标准坐标", parse_frontend_location("30.5,114.3") == "30.5,114.3")
check("中文逗号+空格", parse_frontend_location("30.5， 114.3") == "30.5,114.3")
check("地址文本返回None", parse_frontend_location("湖北省武汉市洪山区") is None)
check("纬度越界拒绝", parse_frontend_location("99.5,114.3") is None)
check("空输入", parse_frontend_location("  ") is None)

print("\n[5.5] 坐标系前缀声明 (wgs84/gcj02/bd09)")
from infrastructure.tools.local.location_service import _gcj02_to_bd09
bd_ref = parse_frontend_location("30.5,114.3")
check("bd09 前缀原样使用", parse_frontend_location("bd09:30.5,114.3") == bd_ref)
check("baidu 别名", parse_frontend_location("baidu:30.5,114.3") == bd_ref)
r_gps = parse_frontend_location("wgs84:30.5928,114.3055")
lng_ref, lat_ref = wgs84_to_bd09(114.3055, 30.5928)
check(f"wgs84 前缀触发转换 (实际 {r_gps})", r_gps == f"{lat_ref:.6f},{lng_ref:.6f}" and r_gps != "30.5928,114.3055")
lng_ref, lat_ref = _gcj02_to_bd09(114.3055, 30.5928)
check(f"gcj02 前缀触发转换 (实际 {parse_frontend_location('gcj02:30.5928,114.3055')})",
      parse_frontend_location("gcj02:30.5928,114.3055") == f"{lat_ref:.6f},{lng_ref:.6f}")
check("gps 别名等效 wgs84", parse_frontend_location("gps:30.5928,114.3055") == r_gps)
check("非法前缀按文本处理", parse_frontend_location("时间:12:30") is None)
check("前缀+越界坐标拒绝", parse_frontend_location("wgs84:99.5,114.3") is None)

print("\n[6] 定位 TTL 过期")
loc_gps = ResolvedLocation("30.5,114.3", LocationSource.FRONTEND_GPS, resolved_at=time.time() - 3 * 3600)
loc_txt = ResolvedLocation("30.5,114.3", LocationSource.USER_TEXT, resolved_at=time.time() - 3 * 3600)
loc_now = ResolvedLocation("30.5,114.3", LocationSource.USER_TEXT)
check("GPS 3小时未过期 (TTL 24h)", not loc_gps.is_expired())
check("文本 3小时已过期 (TTL 2h)", loc_txt.is_expired())
check("刚解析未过期", not loc_now.is_expired())

print("\n[7] WGS-84 -> BD-09 坐标转换")
bd_lng, bd_lat = wgs84_to_bd09(114.3055, 30.5928)
dlat, dlng = bd_lat - 30.5928, bd_lng - 114.3055
check(f"武汉偏移量级合理 (dlat={dlat:.5f}, dlng={dlng:.5f})", 0.001 < abs(dlat) < 0.03 and 0.001 < abs(dlng) < 0.03)
o_lng, o_lat = wgs84_to_bd09(-0.1, 51.5)   # 境外坐标原样返回
check("境外坐标不转换", o_lng == -0.1 and o_lat == 51.5)

print("\n[8] 公网 IP 过滤 is_public_ip")
check("私网 192.168 拒绝", not is_public_ip("192.168.1.3"))
check("本机 127.0.0.1 拒绝", not is_public_ip("127.0.0.1"))
check("空 IP 拒绝", not is_public_ip(""))
check("公网 114.247.50.2 通过", is_public_ip("114.247.50.2"))

print("\n[9] 合并去重 merge_and_dedup (DB 优先)")
db = [{"name": "联想客户服务中心(武汉平安大厦店)", "address": "中山大道818号", "tel": "027-82880099",
       "lat": 30.5822, "lng": 114.2825, "is_official": True}]
online_dup_tel = [{"name": "联想客户服务中心(武汉平安大厦店)", "address": "武汉市江汉区中山大道818号平安大厦",
                   "tel": "02782880099", "lat": 30.5823, "lng": 114.2826}]
online_dup_pos = [{"name": "联想客户服务中心(武汉平安大厦店)", "address": "平安大厦39楼", "tel": "",
                   "lat": 30.58225, "lng": 114.28255}]
online_new = [{"name": "联想客户服务中心(武汉光谷店)", "address": "珞喻路726号", "tel": "027-87654321",
               "lat": 30.5065, "lng": 114.3942}]
merged = merge_and_dedup(db, online_dup_tel + online_dup_pos + online_new, "30.5,114.3")
check(f"电话重复被合并 (结果 {len(merged)} 条)", len(merged) == 2)
merged2 = merge_and_dedup([], online_dup_pos + online_new, "30.5,114.3")
check(f"位置+名称重复被合并 (结果 {len(merged2)} 条)", len(merged2) == 2)
check("DB电话缺失时由在线补全", merged[0].get("tel") == "027-82880099")

print("\n[10] 多关键词组内去重逻辑 (名称唯一)")
online_multi = [
    {"name": "联想客户服务中心(武汉平安大厦店)", "lat": 30.5822, "lng": 114.2825, "distance": None, "tel": "t1"},
    {"name": "联想客户服务中心(武汉平安大厦店)", "lat": 30.5822, "lng": 114.2825, "distance": 1234, "tel": "t2"},
    {"name": "联想客服中心", "lat": 30.50, "lng": 114.30, "distance": 0, "tel": "t3"},
]
seen, uniq = set(), []
for p in online_multi:
    if p["name"] not in seen:
        uniq.append(p); seen.add(p["name"])
check(f"同名POI去重 (3->2, 实际 {len(uniq)})", len(uniq) == 2)

print("\n[11] 会话记录迁移逻辑 (旧键 user_location -> location_record)")
from infrastructure.tools.local.location_service import resolve_user_location

class FakeSession:
    def __init__(self, ctx):
        self._ctx = dict(ctx)
    @property
    def context(self):
        return self._ctx

async def test_migration():
    s = FakeSession({"user_location": "30.5928,114.3055"})
    loc = await resolve_user_location(s, location_hint="")
    return loc, s

loc, s = asyncio.run(test_migration())
check("旧键迁移成功且坐标正确", loc is not None and loc.coords == "30.5928,114.3055")
check("迁移后写入新键 location_record", "location_record" in s.context)

async def test_hint_priority():
    # hint 优先于缓存: 使用不可 geocode 的环境 (无 AK 时 geocode 返回 None, 应回退缓存)
    s = FakeSession({"location_record": {"coords": "31.2304,121.4737", "source": "user_text",
                                          "display": "上海", "ts": time.time()}})
    loc = await resolve_user_location(s, location_hint="")
    return loc

loc = asyncio.run(test_hint_priority())
check("有效缓存可直接使用", loc is not None and loc.coords == "31.2304,121.4737")

async def test_unknown():
    s = FakeSession({"client_ip": "192.168.1.5"})   # 私网 IP: 无 hint/缓存/IP 可用
    loc = await resolve_user_location(s, location_hint="")
    return loc

loc = asyncio.run(test_unknown())
check("全链路失败返回 None (触发追问)", loc is None)

print("\n[12] 追问提示常量存在")
from infrastructure.tools.local.location_service import LOCATION_REQUIRED_NOTICE
check("包含追问指引", "location_hint" in LOCATION_REQUIRED_NOTICE and "请问" in LOCATION_REQUIRED_NOTICE)

# ---------------------------------------------------------------------------
print(f"\n{'=' * 50}")
print(f"测试结果: {PASS} 通过, {FAIL} 失败")
sys.exit(0 if FAIL == 0 else 1)
