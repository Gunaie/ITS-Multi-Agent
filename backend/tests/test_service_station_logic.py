"""
业务服务专家 - 纯逻辑单元测试（无外部服务依赖）

覆盖: 电话归一化匹配 / 名称相似度 / 地址结构比对 / 坐标转换 /
     前端定位解析 / 定位TTL / haversine / IP过滤 / 多关键词去重 /
     定位解析链路（含旧键迁移、缓存复用、全失败追问）

运行:
    pytest backend/tests/test_service_station_logic.py -v
"""
import os
import sys
import time
import asyncio

# 兼容直接以脚本方式运行 (python test_service_station_logic.py)
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _APP_DIR)
sys.path.insert(0, _BACKEND_DIR)

from infrastructure.tools.local.service_station import (
    phone_match, normalize_name, name_ratio,
    addr_jaccard, haversine, merge_and_dedup,
)
from infrastructure.tools.local.location_service import (
    parse_frontend_location, ResolvedLocation, LocationSource, is_public_ip,
    wgs84_to_bd09, resolve_user_location, LOCATION_REQUIRED_NOTICE, _gcj02_to_bd09,
)


# ---------------------------------------------------------------------------
# [1] 电话归一化匹配 phone_match
# ---------------------------------------------------------------------------
def test_phone_match_normalization():
    assert phone_match("400-168-2825", "4001682825")                  # 格式差异
    assert phone_match("+86 027-82880099", "02782880099")             # 国际区号
    assert phone_match("027-82880099-101", "02782880099")             # 分机互含
    assert phone_match("01085996601", "85996601")                     # 尾8位一致
    assert not phone_match("13800138000", "13900139000")              # 不同号码
    assert not phone_match("123", "1234")                             # 过短号码
    assert not phone_match("", "02782880099")                         # 空号码


def test_phone_match_multi_numbers():
    # 多电话字段拆分匹配（百度 POI 常返回逗号/分号分隔的多号码）
    assert phone_match("15377676079,18107108004", "15377676079")
    assert phone_match("02782880099", "02782880099;13800138000")      # 多电话双向
    assert not phone_match("15377676079,18107108004", "02782880099")  # 多电话均不匹配


# ---------------------------------------------------------------------------
# [2] 名称相似度 name_ratio
# ---------------------------------------------------------------------------
def test_name_similarity():
    assert name_ratio("联想客户服务中心(武汉平安大厦店)", "联想客户服务中心") == 1.0  # 同店去后缀
    assert normalize_name("联想 客户服务中心") == "联想客户服务中心"                  # 空白归一
    assert name_ratio("武汉联想维修中心", "联想客户服务中心") < 1.0                  # 不同业态名称低于1


# ---------------------------------------------------------------------------
# [3] 地址结构比对 addr_jaccard
# ---------------------------------------------------------------------------
def test_addr_jaccard():
    assert addr_jaccard("武汉市江汉区中山大道818号平安大厦39楼",
                        "江汉区中山大道818号平安大厦39楼3914室") >= 0.4              # 同址相似
    assert addr_jaccard("中山大道818号", "中山大道100号") < 0.4                     # 同路不同门牌不误判


# ---------------------------------------------------------------------------
# [4] haversine 直线距离
# ---------------------------------------------------------------------------
def test_haversine():
    wh2bj = haversine(30.5928, 114.3055, 39.9042, 116.4074)
    assert 1020 <= wh2bj <= 1090                                # 武汉->北京约1053km
    assert haversine(30.5, 114.3, 30.5, 114.3) < 1e-6           # 同点为0


# ---------------------------------------------------------------------------
# [5] 前端定位解析 parse_frontend_location
# ---------------------------------------------------------------------------
def test_parse_frontend_location():
    assert parse_frontend_location("30.5,114.3") == "30.5,114.3"          # 标准坐标
    assert parse_frontend_location("30.5， 114.3") == "30.5,114.3"        # 中文逗号+空格
    assert parse_frontend_location("湖北省武汉市洪山区") is None           # 地址文本返回None
    assert parse_frontend_location("99.5,114.3") is None                  # 纬度越界拒绝
    assert parse_frontend_location("  ") is None                          # 空输入


def test_coordinate_prefix_declaration():
    bd_ref = parse_frontend_location("30.5,114.3")
    assert parse_frontend_location("bd09:30.5,114.3") == bd_ref           # bd09 前缀原样使用
    assert parse_frontend_location("baidu:30.5,114.3") == bd_ref          # baidu 别名

    r_gps = parse_frontend_location("wgs84:30.5928,114.3055")
    lng_ref, lat_ref = wgs84_to_bd09(114.3055, 30.5928)
    assert r_gps == f"{lat_ref:.6f},{lng_ref:.6f}" and r_gps != "30.5928,114.3055"  # wgs84 触发转换

    lng_ref, lat_ref = _gcj02_to_bd09(114.3055, 30.5928)
    assert parse_frontend_location("gcj02:30.5928,114.3055") == f"{lat_ref:.6f},{lng_ref:.6f}"  # gcj02 触发转换
    assert parse_frontend_location("gps:30.5928,114.3055") == r_gps       # gps 别名等效 wgs84
    assert parse_frontend_location("时间:12:30") is None                  # 非法前缀按文本处理
    assert parse_frontend_location("wgs84:99.5,114.3") is None            # 前缀+越界坐标拒绝


# ---------------------------------------------------------------------------
# [6] 定位 TTL 过期
# ---------------------------------------------------------------------------
def test_location_ttl():
    loc_gps = ResolvedLocation("30.5,114.3", LocationSource.FRONTEND_GPS,
                               resolved_at=time.time() - 3 * 3600)
    loc_txt = ResolvedLocation("30.5,114.3", LocationSource.USER_TEXT,
                               resolved_at=time.time() - 3 * 3600)
    loc_now = ResolvedLocation("30.5,114.3", LocationSource.USER_TEXT)
    assert not loc_gps.is_expired()     # GPS 3小时未过期 (TTL 24h)
    assert loc_txt.is_expired()         # 文本 3小时已过期 (TTL 2h)
    assert not loc_now.is_expired()     # 刚解析未过期


# ---------------------------------------------------------------------------
# [7] WGS-84 -> BD-09 坐标转换
# ---------------------------------------------------------------------------
def test_wgs84_to_bd09():
    bd_lng, bd_lat = wgs84_to_bd09(114.3055, 30.5928)
    dlat, dlng = bd_lat - 30.5928, bd_lng - 114.3055
    assert 0.001 < abs(dlat) < 0.03 and 0.001 < abs(dlng) < 0.03         # 武汉偏移量级合理
    o_lng, o_lat = wgs84_to_bd09(-0.1, 51.5)
    assert o_lng == -0.1 and o_lat == 51.5                               # 境外坐标不转换


# ---------------------------------------------------------------------------
# [8] 公网 IP 过滤 is_public_ip
# ---------------------------------------------------------------------------
def test_is_public_ip():
    assert not is_public_ip("192.168.1.3")     # 私网 192.168 拒绝
    assert not is_public_ip("127.0.0.1")       # 本机拒绝
    assert not is_public_ip("")                # 空 IP 拒绝
    assert is_public_ip("114.247.50.2")        # 公网通过


# ---------------------------------------------------------------------------
# [9] 合并去重 merge_and_dedup (DB 优先)
# ---------------------------------------------------------------------------
def test_merge_and_dedup():
    db = [{"name": "联想客户服务中心(武汉平安大厦店)", "address": "中山大道818号", "tel": "027-82880099",
           "lat": 30.5822, "lng": 114.2825, "is_official": True}]
    online_dup_tel = [{"name": "联想客户服务中心(武汉平安大厦店)", "address": "武汉市江汉区中山大道818号平安大厦",
                       "tel": "02782880099", "lat": 30.5823, "lng": 114.2826}]
    online_dup_pos = [{"name": "联想客户服务中心(武汉平安大厦店)", "address": "平安大厦39楼", "tel": "",
                       "lat": 30.58225, "lng": 114.28255}]
    online_new = [{"name": "联想客户服务中心(武汉光谷店)", "address": "珞喻路726号", "tel": "027-87654321",
                   "lat": 30.5065, "lng": 114.3942}]
    merged = merge_and_dedup(db, online_dup_tel + online_dup_pos + online_new, "30.5,114.3")
    assert len(merged) == 2                    # 电话重复被合并
    assert merged[0].get("tel") == "027-82880099"  # DB电话缺失时由在线补全

    merged2 = merge_and_dedup([], online_dup_pos + online_new, "30.5,114.3")
    assert len(merged2) == 2                   # 位置+名称重复被合并


# ---------------------------------------------------------------------------
# [10] 多关键词组内去重逻辑 (名称唯一)
# ---------------------------------------------------------------------------
def test_multi_keyword_dedup():
    online_multi = [
        {"name": "联想客户服务中心(武汉平安大厦店)", "lat": 30.5822, "lng": 114.2825, "distance": None, "tel": "t1"},
        {"name": "联想客户服务中心(武汉平安大厦店)", "lat": 30.5822, "lng": 114.2825, "distance": 1234, "tel": "t2"},
        {"name": "联想客服中心", "lat": 30.50, "lng": 114.30, "distance": 0, "tel": "t3"},
    ]
    seen, uniq = set(), []
    for p in online_multi:
        if p["name"] not in seen:
            uniq.append(p)
            seen.add(p["name"])
    assert len(uniq) == 2                      # 同名POI去重 3->2


# ---------------------------------------------------------------------------
# [11] 定位解析链路 resolve_user_location
# ---------------------------------------------------------------------------
class FakeSession:
    def __init__(self, ctx):
        self._ctx = dict(ctx)

    @property
    def context(self):
        return self._ctx


def test_migration_old_key():
    async def scenario():
        s = FakeSession({"user_location": "30.5928,114.3055"})  # 旧键 user_location
        loc = await resolve_user_location(s, location_hint="")
        return loc, s

    loc, s = asyncio.run(scenario())
    assert loc is not None and loc.coords == "30.5928,114.3055"   # 旧键迁移成功且坐标正确
    assert "location_record" in s.context                         # 迁移后写入新键


def test_valid_cache_used():
    async def scenario():
        s = FakeSession({"location_record": {"coords": "31.2304,121.4737", "source": "user_text",
                                             "display": "上海", "ts": time.time()}})
        return await resolve_user_location(s, location_hint="")

    loc = asyncio.run(scenario())
    assert loc is not None and loc.coords == "31.2304,121.4737"    # 有效缓存可直接使用


def test_all_fail_returns_none():
    async def scenario():
        s = FakeSession({"client_ip": "192.168.1.5"})   # 私网 IP: 无 hint/缓存/IP 可用
        return await resolve_user_location(s, location_hint="")

    loc = asyncio.run(scenario())
    assert loc is None                                            # 全链路失败返回 None (触发追问)


# ---------------------------------------------------------------------------
# [12] 追问提示常量
# ---------------------------------------------------------------------------
def test_location_required_notice():
    assert "location_hint" in LOCATION_REQUIRED_NOTICE and "请问" in LOCATION_REQUIRED_NOTICE
