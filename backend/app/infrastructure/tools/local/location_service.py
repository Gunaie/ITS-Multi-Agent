"""
统一用户定位服务

设计要点:
1. 全链路统一使用百度 BD-09 坐标系（与百度 geocode / POI / routematrix 一致）。
   前端 location 契约: 传 "lat,lng" 视为 BD-09 坐标；传地址文本则惰性走 geocode。
2. 定位分级（优先级从高到低）:
   USER_TEXT(本轮 LLM 提取的地点) > FRONTEND_GPS 缓存 > 文本缓存 > IP 兜底 > UNKNOWN(追问)
3. 缓存记录带来源与时间戳，按来源设置 TTL，杜绝"上周武汉、今天上海"的过期定位。
4. 定位失败绝不静默兜底默认城市，返回 None 由上层向用户追问。
"""
import re
import math
import time
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import httpx

from common.infrastructure.logging.logger import logger

# ---------------------------------------------------------------------------
# 坐标转换 (WGS-84 -> GCJ-02 -> BD-09)，用于 IP 定位结果归一化
# ---------------------------------------------------------------------------
_PI = math.pi
_X_PI = _PI * 3000.0 / 180.0
_A = 6378245.0                    # 长半轴
_EE = 0.00669342162296594323      # 偏心率平方


def _out_of_china(lng: float, lat: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * _PI) + 40.0 * math.sin(y / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * _PI) + 320.0 * math.sin(y * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * _PI) + 20.0 * math.sin(2.0 * x * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * _PI) + 40.0 * math.sin(x / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * _PI) + 300.0 * math.sin(x / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def _wgs84_to_gcj02(lng: float, lat: float) -> tuple:
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return lng + dlng, lat + dlat


def _gcj02_to_bd09(lng: float, lat: float) -> tuple:
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * _X_PI)
    bd_lng = z * math.cos(theta) + 0.0065
    bd_lat = z * math.sin(theta) + 0.006
    return bd_lng, bd_lat


def wgs84_to_bd09(lng: float, lat: float) -> tuple:
    """WGS-84 -> BD-09，返回 (bd_lng, bd_lat)。境外坐标原样返回"""
    if _out_of_china(lng, lat):
        return lng, lat
    gcj_lng, gcj_lat = _wgs84_to_gcj02(lng, lat)
    return _gcj02_to_bd09(gcj_lng, gcj_lat)


# ---------------------------------------------------------------------------
# 定位数据结构与来源
# ---------------------------------------------------------------------------
class LocationSource(str, Enum):
    FRONTEND_GPS = "frontend_gps"   # 前端传来的坐标 (契约: BD-09)
    USER_TEXT = "user_text"         # 从用户话语解析的地点
    SESSION_CACHE = "session_cache" # 会话缓存的历史位置
    IP_FALLBACK = "ip_fallback"     # IP 粗略定位


# 各来源缓存有效期（秒）。GPS 相对稳定可缓存一天；文本地点与 IP 仅短期有效。
_SOURCE_TTL = {
    LocationSource.FRONTEND_GPS: 24 * 3600,
    LocationSource.USER_TEXT: 2 * 3600,
    LocationSource.IP_FALLBACK: 30 * 60,
    LocationSource.SESSION_CACHE: 0,
}

# "lat,lng" 格式校验（支持中文逗号与空格分隔）
_COORDS_RE = re.compile(
    r"^\s*([0-9]{1,2}(?:\.[0-9]+)?)[,，\s]+([0-9]{1,3}(?:\.[0-9]+)?)\s*$"
)

# 私网/本机地址（这类 IP 做 IP 定位只能解析到服务器自身位置，必须跳过）
_PRIVATE_IP_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.|169\.254\.|fc|fd|::1|localhost)"
)


@dataclass
class ResolvedLocation:
    coords: str                     # "lat,lng" (BD-09)
    source: LocationSource
    display_name: str = ""          # 可读地名（如 "武汉光谷"），可为空
    resolved_at: float = field(default_factory=time.time)

    @property
    def lat(self) -> Optional[float]:
        try:
            return float(self.coords.split(",")[0])
        except Exception:
            return None

    @property
    def lng(self) -> Optional[float]:
        try:
            return float(self.coords.split(",")[1])
        except Exception:
            return None

    def is_expired(self) -> bool:
        ttl = _SOURCE_TTL.get(self.source, 0)
        if ttl <= 0:
            return False
        return (time.time() - self.resolved_at) > ttl


def is_public_ip(ip: str) -> bool:
    """仅公网 IP 才具备 IP 定位意义（私网 IP 只能解析到服务器自身）"""
    if not ip:
        return False
    return _PRIVATE_IP_RE.match(ip.strip().lower()) is None


# ---------------------------------------------------------------------------
# 定位失败时的追问提示（返回给 Agent，由 Agent 向用户提问）
# ---------------------------------------------------------------------------
LOCATION_REQUIRED_NOTICE = (
    "⚠️ 无法确定用户位置。\n"
    "请直接向用户提问以确认位置，例如：\"请问您在哪个城市或区域？\"\n"
    "获得答复后，再次调用本工具，并将地点填入 location_hint 参数。"
)


# ---------------------------------------------------------------------------
# 各级定位手段
# ---------------------------------------------------------------------------
# 前端 location 坐标系前缀别名表（小写匹配）
_COORD_DATUM_PREFIXES = {
    "wgs84": "wgs84", "wgs": "wgs84", "gps": "wgs84",
    "gcj02": "gcj02", "gcj": "gcj02", "mars": "gcj02",
    "bd09": "bd09", "bd09ll": "bd09", "baidu": "bd09",
}


def parse_frontend_location(raw: str) -> Optional[str]:
    """
    解析前端 location 参数。契约：
    - "lat,lng" -> 默认视为 BD-09 坐标，返回归一化 "lat,lng"
    - "wgs84:lat,lng" / "gps:lat,lng"   -> 浏览器/手机 GPS 坐标，自动转 BD-09
    - "gcj02:lat,lng"  / "mars:lat,lng" -> 高德/腾讯 SDK 坐标，自动转 BD-09
    - "bd09:lat,lng"   / "baidu:lat,lng"-> 百度坐标，原样使用
    - 地址文本 -> 返回 None（由调用方存为待解析 hint，工具侧惰性 geocode）
    """
    if not raw or not raw.strip():
        return None

    s = raw.strip()
    datum = "bd09"  # 缺省坐标系: BD-09（与后端全链路一致）
    if ":" in s:
        prefix, rest = s.split(":", 1)
        d = _COORD_DATUM_PREFIXES.get(prefix.strip().lower())
        if d and rest.strip():
            datum, s = d, rest.strip()
        else:
            # 前缀不合法，按地址文本处理
            return None

    m = _COORDS_RE.match(s)
    if not m:
        return None
    lat, lng = float(m.group(1)), float(m.group(2))
    # 中国范围粗校验，防止传入非法数值
    if not (3.0 <= lat <= 54.0 and 73.0 <= lng <= 136.0):
        logger.warning(f"Frontend location out of range, ignored: {raw!r}")
        return None

    if datum == "wgs84":
        bd_lng, bd_lat = wgs84_to_bd09(lng, lat)
        return f"{bd_lat:.6f},{bd_lng:.6f}"
    if datum == "gcj02":
        bd_lng, bd_lat = _gcj02_to_bd09(lng, lat)
        return f"{bd_lat:.6f},{bd_lng:.6f}"
    return f"{lat},{lng}"


async def geocode_address(address: str) -> Optional[ResolvedLocation]:
    """将用户提供的地点文本解析为 BD-09 坐标"""
    from config.settings import settings
    from infrastructure.tools.local.baidu_map_tool import get_baidu_client

    ak = settings.BAIDU_MAP_AK
    if not ak:
        logger.info("Baidu Map AK missing, geocode unavailable")
        return None

    url = "https://api.map.baidu.com/geocoding/v3/"
    params = {"ak": ak, "address": address, "output": "json"}
    # 从 hint 提取城市名传 city 参数，约束搜索范围。
    # 不传 city 时百度可能把"武汉工程大学流芳校区"误解析到江西九江同名地点，
    # 传 city="武汉"后百度限定在武汉范围内搜索，消除跨城市误解析。
    city = _extract_city_from_hint(address)
    if city:
        params["city"] = city
    try:
        client = get_baidu_client()
        logger.info(f"Geocoding location hint: {address}" + (f" (city={city})" if city else ""))
        response = await client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 0:
                loc = data["result"]["location"]
                return ResolvedLocation(
                    coords=f"{loc['lat']},{loc['lng']}",
                    source=LocationSource.USER_TEXT,
                    display_name=address,
                )
            # 2: 参数无效 / 无法解析等，均为正常业务失败
            logger.info(f"Baidu geocode miss for {address!r}: status={data.get('status')}")
    except Exception as e:
        logger.warning(f"Baidu geocode failed for {address!r}: {e}")
    return None


# 中国主要城市名（直辖市+省会+副省级+计划单列+主要地级市），用于 hint 前缀匹配
# 不含"市"后缀，匹配时按长度降序尝试（避免"北京"匹配到"北京路"）
_KNOWN_CITIES = (
    # 直辖市
    "北京", "上海", "天津", "重庆",
    # 省会/副省级
    "武汉", "广州", "深圳", "成都", "杭州", "南京", "西安", "长沙", "沈阳", "青岛",
    "济南", "郑州", "合肥", "福州", "厦门", "南昌", "太原", "贵阳", "昆明", "兰州",
    "长春", "哈尔滨", "石家庄", "呼和浩特", "乌鲁木齐", "银川", "西宁", "拉萨",
    "海口", "南宁", "宁波", "大连", "无锡", "苏州", "温州", "佛山", "东莞", "珠海",
    "中山", "惠州", "汕头", "徐州", "常州", "南通", "扬州", "镇江", "泰州",
    # 湖北/其他
    "宜昌", "襄阳", "岳阳", "衡阳", "株洲", "九江", "大庆", "包头", "洛阳", "烟台",
    "潍坊", "临沂", "嘉兴", "金华", "台州", "绍兴", "泉州", "赣州", "芜湖", "绵阳",
    "咸阳", "宝鸡", "桂林", "柳州",
)

def _extract_city_from_hint(hint: str) -> str:
    """从地点文本提取城市名，用于 geocode 的 city 参数约束搜索范围。

    策略: 先匹配"XX市"显式城市标记，再按已知城市名前缀匹配（按长度降序避免短名误匹配）。
    """
    if not hint:
        return ""
    import re
    # 1. 显式"XX市"模式（如"武汉市洪山区" → "武汉"）
    m = re.search(r'([\u4e00-\u9fa5]{2,5})市', hint)
    if m:
        return m.group(1)
    # 2. 已知城市名前缀匹配（按长度降序，避免"北京"匹配到"北京路"场景下取到更长匹配）
    for city in sorted(_KNOWN_CITIES, key=len, reverse=True):
        if city in hint:
            return city
    return ""


async def get_ip_location(client_ip: str) -> Optional[ResolvedLocation]:
    """
    IP 定位兜底。仅接受公网客户端 IP：
    - 私网/本机 IP 只能解析到服务器自身位置，直接放弃
    - ip-api.com 返回 WGS-84，必须转换为 BD-09 后才能供百度 API 使用
    """
    if not is_public_ip(client_ip):
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{client_ip}",
                params={"lang": "zh-CN", "fields": "status,lat,lon,city"},
            )
        data = resp.json()
        if data.get("status") == "success":
            lng, lat = float(data["lon"]), float(data["lat"])
            bd_lng, bd_lat = wgs84_to_bd09(lng, lat)
            logger.info(f"IP location success: {data.get('city', '')} -> {bd_lat:.6f},{bd_lng:.6f}")
            return ResolvedLocation(
                coords=f"{bd_lat:.6f},{bd_lng:.6f}",
                source=LocationSource.IP_FALLBACK,
                display_name=str(data.get("city", "")),
            )
    except Exception as e:
        logger.info(f"IP location failed for {client_ip}: {e}")
    return None


# ---------------------------------------------------------------------------
# 会话缓存记录的存取
# ---------------------------------------------------------------------------
def _save_record(session, loc: ResolvedLocation) -> None:
    try:
        if session is not None and hasattr(session, "context"):
            session.context["location_record"] = {
                "coords": loc.coords,
                "source": loc.source.value,
                "display": loc.display_name,
                "ts": loc.resolved_at,
            }
    except Exception as e:
        logger.warning(f"Failed to save location record: {e}")


def _load_record(ctx_dict: dict) -> Optional[ResolvedLocation]:
    rec = ctx_dict.get("location_record")
    if not isinstance(rec, dict) or not rec.get("coords"):
        return None
    try:
        source = LocationSource(rec.get("source", LocationSource.USER_TEXT.value))
    except ValueError:
        source = LocationSource.USER_TEXT
    return ResolvedLocation(
        coords=str(rec["coords"]),
        source=source,
        display_name=str(rec.get("display", "")),
        resolved_at=float(rec.get("ts", 0) or 0),
    )


# ---------------------------------------------------------------------------
# 统一定位入口（分级解析）
# ---------------------------------------------------------------------------
async def resolve_user_location(session, location_hint: str = "") -> Optional[ResolvedLocation]:
    """
    分级解析用户位置，返回 None 表示完全无法定位（上层应向用户追问）。

    优先级:
    1. location_hint（本轮 LLM 提取的地点）或前端遗留的待解析文本 -> geocode
    2. 会话缓存记录（按来源 TTL 校验，GPS 24h / 文本 2h / IP 30min）
    3. IP 兜底（仅公网客户端 IP，WGS-84 -> BD-09）
    4. 返回 None，绝不静默兜底默认城市
    """
    ctx_dict = {}
    if session is not None and hasattr(session, "context"):
        try:
            ctx_dict = session.context or {}
        except Exception:
            ctx_dict = {}

    # 0) 旧版 user_location 键迁移（无时间戳，按文本来源从当前时间起算 TTL）
    if "location_record" not in ctx_dict and ctx_dict.get("user_location"):
        ctx_dict["location_record"] = {
            "coords": str(ctx_dict["user_location"]),
            "source": LocationSource.USER_TEXT.value,
            "display": "",
            "ts": time.time(),
        }

    # 1) 本轮显式地点：LLM 提取的 location_hint / 前端留下的待解析文本
    hint = (location_hint or "").strip() or str(ctx_dict.get("location_hint_pending") or "").strip()
    if hint and len(hint) >= 2:
        # 无论成功与否都消费掉 pending，避免后续每轮重复 geocode
        ctx_dict.pop("location_hint_pending", None)
        try:
            loc = await asyncio.wait_for(geocode_address(hint), timeout=4.0)
        except asyncio.TimeoutError:
            logger.info(f"Geocode hint timed out: {hint!r}")
            loc = None
        if loc:
            logger.info(f"Location resolved via hint {hint!r} -> {loc.coords}")
            _save_record(session, loc)
            return loc

    # 2) 会话缓存（按来源 TTL 校验）
    cached = _load_record(ctx_dict)
    if cached and not cached.is_expired():
        return cached
    if cached:
        logger.info(f"Session location expired (source={cached.source.value}), discarding")

    # 3) IP 兜底（仅公网客户端 IP）
    client_ip = str(ctx_dict.get("client_ip") or "").strip()
    if client_ip:
        loc = await get_ip_location(client_ip)
        if loc:
            _save_record(session, loc)
            return loc

    # 4) 完全无法定位，交由上层追问用户
    return None
