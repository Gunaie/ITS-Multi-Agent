import math
import re
import asyncio
from urllib.parse import quote
from difflib import SequenceMatcher
from infrastructure.database.database_pool import pool
from agents import function_tool, RunContextWrapper
from common.infrastructure.logging.logger import logger

# 统一检索口径：在线 POI 与本地 DB 均按此半径筛选（公里）
SEARCH_RADIUS_KM = 200
# 路网测距粗筛数量（百度 routematrix 单次上限 50，留余量）
ROAD_DIST_TOP_N = 10

def haversine(lat1, lon1, lat2, lon2):
    """计算两个经纬度之间的距离（公里）"""
    R = 6371  # 地球半径
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _bbox(coords: str, radius_km: float) -> tuple:
    """以坐标为中心的经纬度粗筛框（比实际半径大 20% 余量补偿 bbox 近似）"""
    lat, lng = map(float, coords.split(','))
    dlat = radius_km * 1.2 / 111.32
    dlng = radius_km * 1.2 / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def _nearest_db_fallback(db_pois: list, coords: str, max_count: int = 2) -> list:
    """官方授权库兜底：按直线距离取最近的官方网点，保证回答中至少存在一个 ✅ 条目。

    仅使用授权库自有字段（名称/地址/电话/坐标），不依赖地图侧核验，诚实标注来源与距离口径。
    """
    try:
        u_lat, u_lng = map(float, coords.split(','))
    except (ValueError, AttributeError):
        return []
    items = []
    for st in db_pois or []:
        lat, lng = st.get('lat'), st.get('lng')
        if lat is None or lng is None:
            continue
        try:
            dist = haversine(u_lat, u_lng, float(lat), float(lng))
        except (ValueError, TypeError):
            continue
        if dist > SEARCH_RADIUS_KM:
            continue
        name = st.get('name', '联想官方服务站')
        addr = st.get('address', '详见官方授权库')
        tel = st.get('phone') or '请以官方授权库为准'
        nav_url = (
            f"https://api.map.baidu.com/marker?location={lat},{lng}"
            f"&title={quote(name)}&output=html&src=webapp.its.agent&coord_type=bd09ll"
        )
        items.append((dist, (
            f"✅ **{name}** (官方授权库直供)\n"
            f"   - 📍 地址: {addr}\n"
            f"   - 📏 距离: 约 {dist:.2f} 公里 (直线距离)\n"
            f"   - 🗺️ [立即查看]({nav_url})\n"
            f"   - 📞 电话: {tel}"
        )))
    items.sort(key=lambda x: x[0])
    return [text for _, text in items[:max_count]]


@function_tool
async def get_nearby_official_repair_stations(ctx: RunContextWrapper, brand: str = "联想", location_hint: str = "") -> str:
    """
    一键式获取用户周边经过官方核验的维修站。
    这是最推荐的高速工具，集成了定位、实时探测和官方核验。

    Args:
        brand: 品牌名称，默认 "联想"
        location_hint: 用户提到的地点线索（如 "武汉光谷"、"朝阳区"、"知春路"）。
            只要用户话语中出现任何地点信息，就必须原样传入该参数；用户未提地点时传空字符串。
    """
    try:
        # 外层硬顶 22s（内部预算: 定位 4s + 检索 8s + 测距 6s = 18s，留 4s 余量）
        return await asyncio.wait_for(_get_nearby_official_repair_stations_impl(ctx, brand, location_hint), timeout=22.0)
    except asyncio.TimeoutError:
        logger.error(f"Integrated tool get_nearby_official_repair_stations timed out after 22s")
        return f"查询{brand}维修站服务响应超时。建议您直接在百度地图中搜索“{brand}官方维修站”。"

async def get_db_official_stations(coords: str, brand: str = "联想") -> list[dict]:
    """
    从本地官方数据库中查询维修站，返回结构化数据。
    使用经纬度 bounding box 粗筛 + haversine 精筛，brand 参数生效。
    """
    if not coords or ',' not in coords:
        return []
    try:
        lat, lng = map(float, coords.split(','))
    except ValueError:
        logger.warning(f"Invalid coords for DB query: {coords!r}")
        return []

    # brand 中文 -> 库内英文标识映射（键统一小写，查询前归一化）
    brand_map = {"联想": "Lenovo", "lenovo": "Lenovo", "thinkpad": "Lenovo"}
    normalized = brand.strip().lower()
    db_brand = brand_map.get(normalized, None)
    if not db_brand:
        # 其他品牌暂无数据库记录，直接交给在线搜索
        logger.info(f"Brand {brand!r} not in local DB scope, skip DB query")
        return []

    lat_min, lat_max, lng_min, lng_max = _bbox(coords, SEARCH_RADIUS_KM)
    conn = pool.connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT name, address, phone, lat, lng FROM service_stations
                   WHERE brand = %s AND lat BETWEEN %s AND %s AND lng BETWEEN %s AND %s""",
                (db_brand, lat_min, lat_max, lng_min, lng_max)
            )
            results = cursor.fetchall()
            
            stations = []
            for row in results:
                s_lat, s_lng = float(row[3]), float(row[4])
                dist = haversine(lat, lng, s_lat, s_lng)
                if dist <= SEARCH_RADIUS_KM:
                    stations.append({
                        "name": row[0],
                        "address": row[1],
                        "tel": row[2],
                        "lat": s_lat,
                        "lng": s_lng,
                        "distance": dist * 1000, # 统一单位为米
                        "is_official": True,
                        "is_from_db": True
                    })
            return stations
    finally:
        conn.close()

async def _get_nearby_official_repair_stations_impl(ctx: RunContextWrapper, brand: str = "联想", location_hint: str = "") -> str:
    logger.info(f"High-speed station search started for brand: {brand}, location_hint: {location_hint!r}")

    session = getattr(ctx, "context", None)

    # 1. 分级解析用户位置 (location_hint > 会话缓存 > IP兜底)，失败则返回追问提示
    from infrastructure.tools.local.location_service import (
        resolve_user_location,
        LOCATION_REQUIRED_NOTICE,
    )
    loc = await resolve_user_location(session, location_hint=location_hint)
    if loc is None:
        logger.info("Location unresolved after full fallback chain, asking user")
        return LOCATION_REQUIRED_NOTICE
    coords = loc.coords
    logger.info(f"Location resolved: source={loc.source.value}, coords={coords}")
    
    # 2. 并行执行联网搜索（多关键词提升召回）和本地数据库查询
    search_radius_m = SEARCH_RADIUS_KM * 1000

    async def search_keyword(kw: str) -> list:
        if not kw:
            return []
        try:
            from infrastructure.tools.local.baidu_map_tool import baidu_around_search
            return await asyncio.wait_for(
                baidu_around_search(coords, kw, radius=search_radius_m), timeout=8.0
            )
        except Exception as e:
            logger.warning(f"Online search failed for {kw!r}: {e}")
            return []

    async def run_online_search():
        # 多组关键词覆盖真实店名（"联想客户服务中心"/"联想授权服务站"等），单关键词漏检严重
        keywords = [f"{brand}客户服务中心", f"{brand}授权服务站", f"{brand}维修"]
        keyword_results = await asyncio.gather(*(search_keyword(kw) for kw in keywords))
        # 同关键词组内先按名称去重（多关键词常命中同一 POI）
        merged, seen = [], set()
        for poi_list in keyword_results:
            for p in poi_list:
                key = str(p.get("name", ""))
                if key and key not in seen:
                    merged.append(p)
                    seen.add(key)
        return merged

    async def run_db_query():
        try:
            return await asyncio.wait_for(get_db_official_stations(coords, brand), timeout=5.0)
        except Exception as e:
            logger.warning(f"DB search failed: {e}")
            return []

    online_pois, db_pois = await asyncio.gather(run_online_search(), run_db_query())

    # 3. 核验在线 POI 并与 DB 记录智能合并去重（DB 优先）
    verified_online = await verify_official_stations(online_pois)
    all_pois = merge_and_dedup(db_pois, verified_online, coords)

    # 3.5 距离兜底：百度未返回 distance 时现算直线距离，杜绝 0 值污染排序
    try:
        u_lat, u_lng = map(float, coords.split(','))
    except ValueError:
        u_lat = u_lng = None
    for p in all_pois:
        if p.get('distance') in (None, 0) and u_lat is not None \
                and p.get('lat') is not None and p.get('lng') is not None:
            p['distance'] = haversine(u_lat, u_lng, float(p['lat']), float(p['lng'])) * 1000

    # 4. 计算路网距离 (按可信直线距离粗筛前 N 个站点，预算 6s)
    if all_pois:
        try:
            from infrastructure.tools.local.baidu_map_tool import baidu_get_distances_batch
            all_pois.sort(key=lambda x: x.get('distance') if x.get('distance') else 9.9e9)
            process_targets = all_pois[:ROAD_DIST_TOP_N]
            
            dest_coords_list = [f"{p.get('lat')},{p.get('lng')}" for p in process_targets]
            road_distances = await asyncio.wait_for(
                baidu_get_distances_batch(coords, dest_coords_list), timeout=6.0
            )
            
            for i, p in enumerate(process_targets):
                if i < len(road_distances) and road_distances[i] is not None:
                    p['road_dist'] = road_distances[i]
                    p['is_road_dist'] = True
                else:
                    p['road_dist'] = round((p.get('distance') or 0) / 1000, 2)
                    p['is_road_dist'] = False
            
            # 对未处理的站点也补齐 road_dist 字段
            for p in all_pois[ROAD_DIST_TOP_N:]:
                p['road_dist'] = round((p.get('distance') or 0) / 1000, 2)
                p['is_road_dist'] = False
        except Exception as e:
            logger.warning(f"Road distance calculation failed: {e}")
            for p in all_pois:
                p['road_dist'] = round((p.get('distance') or 0) / 1000, 2)
                p['is_road_dist'] = False

    # 再次按路网距离排序
    all_pois.sort(key=lambda x: x.get('road_dist', 999))

    # 5. 整合输出
    final_report = f"### 正在为您查询附近的{brand}官方服务网点...\n\n"
    
    nearby_official = []
    nearby_suspicious = []
    nearby_third = []
    
    for poi in all_pois:
        dist = poi.get('road_dist', 999)
        if dist > SEARCH_RADIUS_KM: continue
        
        name = poi.get('name', '未知门店')
        addr = poi.get('address', '详见地图')
        tel = poi.get('tel', poi.get('telephone', '请以地图标记为准'))
        # coord_type=bd09ll 显式声明百度坐标系，消除默认值不确定性导致的定位偏移
        # content(长地址)不塞入URL：地图打开后会自动逆地理编码显示地址，避免长串链接渲染失败
        nav_url = (
            f"https://api.map.baidu.com/marker?location={poi.get('lat')},{poi.get('lng')}"
            f"&title={quote(name)}&output=html&src=webapp.its.agent&coord_type=bd09ll"
        )
        dist_label = "路网距离" if poi.get('is_road_dist') else "直线距离"
        
        entry = f"📍 地址: {addr}\n   - 📏 距离: 约 {dist:.2f} 公里 ({dist_label})\n   - 🗺️ [立即查看]({nav_url})"
        if poi.get('is_official'):
            item = f"✅ **{name}** (官方授权店)\n   - {entry}\n   - 📞 电话: {tel}"
            nearby_official.append(item)
        elif poi.get('is_suspicious'):
            item = f"❓ **{name}** (疑似官方)\n   - {entry}\n   - 💡 提示: 建议致电核实"
            nearby_suspicious.append(item)
        else:
            item = f"⚠️ **{name}** (第三方维修)\n   - {entry}"
            nearby_third.append(item)

    # 构建展示逻辑
    if nearby_official:
        final_report += f"🏆 **官方授权推荐 ({SEARCH_RADIUS_KM}km以内)**\n"
        final_report += "> 🛡️ **双重核验通过**：已比对联想官方授权数据库，以下网点资质真实有效：\n\n"
        final_report += "\n\n".join(nearby_official[:5]) + "\n\n"
    else:
        # ✅ 兜底：在线核验无命中时，直接从官方授权库按距离补录，保证回答中始终存在可信官方入口
        db_fallback = _nearest_db_fallback(db_pois, coords, max_count=2)
        if db_fallback:
            final_report += f"🏆 **官方授权推荐 ({SEARCH_RADIUS_KM}km以内)**\n"
            final_report += "> 🛡️ **官方授权库直供**：地图侧未检索到可在线核验的网点，以下为授权库中距离最近的官方服务站：\n\n"
            final_report += "\n\n".join(db_fallback) + "\n\n"
        else:
            final_report += f"🏆 **官方授权推荐**\n当前 {SEARCH_RADIUS_KM}km 范围内暂无经过数据库双重核验的授权服务站。\n\n"
            final_report += (
                "✅ **联想官方服务热线: 400-100-6000**\n"
                "   - 💡 附近暂未收录实体网点，请致电获取最近的官方服务站信息（官方渠道，放心拨打）\n\n"
            )
    
    if nearby_suspicious or nearby_third:
        final_report += "🔍 **周边其他参考网点**\n"
        final_report += "> 以下为地图搜索结果，可能包含第三方或非官方点，请注意甄别：\n\n"
        if nearby_suspicious:
            final_report += "\n\n".join(nearby_suspicious[:3]) + "\n\n"
        if nearby_third:
            final_report += "\n\n".join(nearby_third[:3]) + "\n\n"

    # 距离预警
    min_dist = min((p.get('road_dist', 999) for p in all_pois), default=999)
    if min_dist > 50 and not nearby_official:
        loc_desc = loc.display_name or coords
        final_report = f"⚠️ **位置提醒**：系统当前基于定位（{loc_desc}）进行搜索。若与您所在地不符，请直接告诉我您的城市或区域。\n\n" + final_report

    if not all_pois:
        final_report = f"抱歉，在您的位置（{loc.display_name or coords}）附近 {SEARCH_RADIUS_KM}km 内暂时没有找到{brand}维修站。"
        
    return final_report


# ---------------------------------------------------------------------------
# 核验辅助: 电话归一化 / 名称相似度 / 地址结构化比对
# ---------------------------------------------------------------------------
def normalize_phone(p: str) -> str:
    """电话归一化: 仅保留数字，去国际区号 86 前缀"""
    digits = ''.join(filter(str.isdigit, p or ''))
    if digits.startswith('86') and len(digits) > 10:
        digits = digits[2:]
    return digits

def normalize_phones(p: str) -> list:
    """多电话拆分归一化: 按逗号/分号/斜杠拆分后逐个归一化，过滤过短结果。
    场景: 百度 POI 常返回 '15377676079,18107108004' 这类多电话字段，
    旧 normalize_phone 会拼成一串导致完全失配。"""
    if not p:
        return []
    parts = re.split(r'[,;；，/、]', p)
    result = []
    for part in parts:
        d = normalize_phone(part)
        if d and len(d) >= 5:
            result.append(d)
    return result

def phone_match(a: str, b: str) -> bool:
    """电话匹配: 全等 / 长号互含(处理区号与分机差异) / 尾8位一致。
    支持多电话字段: 任一号码匹配即通过。"""
    nas, nbs = normalize_phones(a), normalize_phones(b)
    if not nas or not nbs:
        return False
    for na in nas:
        for nb in nbs:
            if na == nb:
                return True
            if (na in nb or nb in na) and min(len(na), len(nb)) >= 7:
                return True
            if len(na) >= 8 and len(nb) >= 8 and na[-8:] == nb[-8:]:
                return True
    return False

def normalize_name(name: str) -> str:
    """名称规范化: 去括号后的门店后缀与空白，统一比较基准"""
    base = re.split(r'[（(]', name or '')[0]
    return re.sub(r'[\s\u3000]', '', base)

def name_ratio(a: str, b: str) -> float:
    """名称相似度 (0~1)"""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()

_ADDR_NUM_RE = re.compile(r'\d+')
_ADDR_LANDMARKS = ["大厦", "广场", "中心", "大道", "路", "街", "巷", "村", "镇", "楼", "层", "室", "号院"]

def _address_tokens(addr: str) -> set:
    """地址结构化: 门牌数字 + 地标词 + 短地标片段"""
    tokens = set()
    if not addr:
        return tokens
    tokens.update(_ADDR_NUM_RE.findall(addr))
    for seg in re.findall(r'[\u4e00-\u9fa5]{2,10}', addr):
        for lm in _ADDR_LANDMARKS:
            if lm in seg:
                tokens.add(seg if len(seg) <= 6 else lm)
    return tokens

def addr_jaccard(a: str, b: str) -> float:
    """地址结构相似度: token 集合 Jaccard (0~1)"""
    ta, tb = _address_tokens(a), _address_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def _load_official_records() -> list:
    """加载官方授权名单 (name, address, phone, lat, lng)"""
    conn = pool.connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT name, address, phone, lat, lng FROM service_stations WHERE brand = 'Lenovo'"
            )
            return cursor.fetchall()
    finally:
        conn.close()

async def verify_official_stations(stations: list[dict]) -> list[dict]:
    """
    核验在线 POI 是否为联想官方授权。
    评分制: 电话(0.6) + 名称相似度(0.25) + 地址结构相似度(0.15)
    判定规则:
      - 电话匹配 且 名称相似度>=0.6  -> 官方
      - 名称相似度>=0.85 且 地址Jaccard>=0.4 -> 官方（无电话时的替代凭证）
    命中后以官方库全字段回填（含坐标，避免同名不同分店位置错乱）。
    """
    if not stations:
        return []

    logger.info(f"Verification started for {len(stations)} stations")
    official_records = _load_official_records()
    if not official_records:
        # 官方库为空时无法核验，全部降级为疑似，交由用户甄别
        for poi in stations:
            poi['is_official'] = False
            poi['is_suspicious'] = "联想" in (poi.get('name') or '')
        return stations

    # 索引加速: 电话 -> 记录, 规范化名称 -> 记录
    phone_idx: dict[str, list] = {}
    name_idx: dict[str, list] = {}
    for rec in official_records:
        np_ = normalize_phone(rec[2])
        if np_:
            phone_idx.setdefault(np_, []).append(rec)
        nk = normalize_name(rec[0])
        if nk:
            name_idx.setdefault(nk, []).append(rec)

    verified_list = []
    for poi in stations:
        poi_name = poi.get("name", "")
        poi_addr = poi.get("address", "")
        poi_tel = poi.get("tel") or poi.get("telephone") or ""

        # 候选集: 电话命中 + 精确名称命中；为空才退化为全量扫描
        candidates: list = []
        if poi_tel:
            for k, recs in phone_idx.items():
                if phone_match(poi_tel, k):
                    candidates.extend(recs)
        nk = normalize_name(poi_name)
        if nk and nk in name_idx:
            candidates.extend(name_idx[nk])
        if not candidates:
            candidates = official_records

        best_score, best_rec, matched = 0.0, None, None
        for rec in candidates:
            nr = name_ratio(poi_name, rec[0])
            pm = phone_match(poi_tel, rec[2]) if (poi_tel and rec[2]) else False
            aj = addr_jaccard(poi_addr, rec[1])
            score = 0.6 * pm + 0.25 * nr + 0.15 * aj
            if score > best_score:
                best_score, best_rec = score, rec
            if (pm and nr >= 0.6) or (nr >= 0.85 and aj >= 0.4):
                matched = rec
                break

        is_official = matched is not None
        poi['is_official'] = is_official
        poi['verify_score'] = round(best_score, 2)
        if is_official and matched is not None:
            # 以官方库数据为准回填全字段（含坐标）
            poi['name'] = matched[0]
            poi['address'] = matched[1]
            if matched[2]:
                poi['tel'] = matched[2]
            try:
                poi['lat'] = float(matched[3])
                poi['lng'] = float(matched[4])
                poi['is_from_db'] = True
            except (TypeError, ValueError):
                pass

        # 疑似官方: 名称含联想且具备服务特征，但未通过评分核验
        poi['is_suspicious'] = (not is_official) and "联想" in poi_name and \
            any(k in poi_name for k in ("服务", "中心", "授权", "售后"))
        verified_list.append(poi)
        logger.info(f"Verify {poi_name!r}: score={best_score:.2f}, official={is_official}")

    return verified_list

def merge_and_dedup(db_pois: list[dict], online_pois: list[dict], coords: str) -> list[dict]:
    """
    DB 优先合并去重: 电话一致 或 (名称相似度>=0.8 且 两店间距<150m) 视为同一门店。
    DB 记录优先，在线记录仅补充缺失字段。
    """
    merged: list = list(db_pois)
    for p in online_pois:
        dup = None
        for q in merged:
            p_tel = p.get("tel") or p.get("telephone") or ""
            q_tel = q.get("tel") or ""
            if p_tel and q_tel and phone_match(p_tel, q_tel):
                dup = q
                break
            if p.get("lat") and p.get("lng") and q.get("lat") and q.get("lng"):
                d = haversine(float(p["lat"]), float(p["lng"]), float(q["lat"]), float(q["lng"]))
                if d < 0.15 and name_ratio(p.get("name", ""), q.get("name", "")) >= 0.8:
                    dup = q
                    break
        if dup is not None:
            if not dup.get("tel") and (p.get("tel") or p.get("telephone")):
                dup["tel"] = p.get("tel") or p.get("telephone")
        else:
            merged.append(p)
    return merged

@function_tool
async def map_uri(location_name: str, lat: float = None, lng: float = None) -> str:
    """
    生成地图导航/搜索链接。

    Args:
        location_name: 地点名称
        lat: 纬度 (可选，提供时生成精确定位标记链接)
        lng: 经度 (可选，提供时生成精确定位标记链接)

    Returns:
        str: 导航链接 Markdown
    """
    if lat is not None and lng is not None:
        # 带坐标的精确标记链接，避免同名地点搜错位置
        url = (
            f"https://api.map.baidu.com/marker?location={lat},{lng}"
            f"&title={location_name}&content={location_name}&output=html&src=webapp.its.agent"
        )
    else:
        url = f"https://map.baidu.com/search?query={location_name}"
    return f"[{location_name} 的地图链接]({url})"
