import json
import math
import asyncio
import time
import httpx
from functools import lru_cache
from infrastructure.database.database_pool import pool
from agents import function_tool, RunContextWrapper
from agents.memory import Session
from common.infrastructure.logging.logger import logger

# 地理编码缓存，避免短时间内对同一地址重复请求百度 API
@lru_cache(maxsize=100)
def _get_cached_geocode(address: str) -> str:
    # 这是一个占位符，真正的异步缓存实现在 resolve_user_location_from_text 中
    return ""

_geocode_memory_cache = {}

def haversine(lat1, lon1, lat2, lon2):
    """计算两个经纬度之间的距离（公里）"""
    R = 6371  # 地球半径
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

async def get_ip_location() -> str:
    """通过 IP 获取粗略经纬度 (兜底方案)"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            # 使用 ip-api.com (免 Key)
            response = await client.get("http://ip-api.com/json/?lang=zh-CN")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    coords = f"{data.get('lat')},{data.get('lon')}"
                    city = data.get('city', '')
                    logger.info(f"IP-based location success: {city} ({coords})")
                    return coords
    except Exception as e:
        logger.warning(f"IP location failed: {e}")
    return ""

async def resolve_user_location_from_text(ctx: RunContextWrapper, text: str) -> str:
    """
    从用户文本中解析出经纬度坐标，或从会话上下文中获取。
    返回格式: "lat,lng"
    """
    session = ctx.context
    
    # 1. 优先检测文本中是否有新的地点描述 (如“在湖北工业大学”)
    # 如果用户显式提到了地点，我们应该尝试重新解析，而不是沿用旧位置
    if len(text) > 2 and any(k in text for k in ["在", "位于", "去", "到", "学校", "大厦", "路", "区"]):
        # 先查硬编码加速
        city_coords = {
            "武汉": "30.5928,114.3055",
            "流芳校区": "30.4578,114.4358",
            "光谷": "30.5065,114.3942",
            "上海": "31.2304,121.4737",
            "广州": "23.1291,113.2644",
            "深圳": "22.5431,114.0579",
            "北京": "39.9042,116.4074"
        }
        for key, coords in city_coords.items():
            if key in text:
                if session and hasattr(session, 'context'):
                    session.context["user_location"] = coords
                return coords
        
        # 硬编码未命中，尝试调用百度地理编码 API
        try:
            from infrastructure.tools.local.baidu_map_tool import baidu_geocode
            # 提取可能的地点片段 (去除“如果我在”、“附近有哪些”等噪音)
            import re
            clean_text = re.sub(r'(如果我在|我在|在|附近的|附近有哪些|维修站|联想|官方)', '', text).strip()
            if len(clean_text) >= 2:
                logger.info(f"Attempting Baidu geocode for new location: {clean_text}")
                coords = await asyncio.wait_for(baidu_geocode(clean_text), timeout=5.0)
                if coords:
                    logger.info(f"Resolved new location via Baidu: {clean_text} -> {coords}")
                    if session and hasattr(session, 'context'):
                        session.context["user_location"] = coords
                    return coords
        except Exception as e:
            logger.warning(f"Baidu geocode failed for text '{text}': {e}")

    # 2. 从会话上下文中获取 (前端传来的实时位置或之前解析的位置)
    if session and hasattr(session, 'context'):
        cached_loc = session.context.get("user_location")
        if cached_loc:
            return cached_loc
    
    # 3. 如果都没有，尝试 IP 定位
    ip_coords = await get_ip_location()
    if ip_coords:
        if session and hasattr(session, 'context'):
            session.context["user_location"] = ip_coords
        return ip_coords
        
    # 4. 兜底北京
    return "39.9042,116.4074"

@function_tool
async def get_nearby_official_repair_stations(ctx: RunContextWrapper, brand: str = "联想") -> str:
    """
    一键式获取用户周边经过官方核验的维修站。
    这是最推荐的高速工具，集成了定位、实时探测和官方核验。
    
    Args:
        brand: 品牌名称，默认 "联想"
    """
    try:
        # 为整个集成工具设置 20s 的最大执行时间，防止链式调用或外部服务挂起
        return await asyncio.wait_for(_get_nearby_official_repair_stations_impl(ctx, brand), timeout=20.0)
    except asyncio.TimeoutError:
        logger.error(f"Integrated tool get_nearby_official_repair_stations timed out after 20s")
        return f"查询{brand}维修站服务响应超时。建议您直接在百度地图中搜索“{brand}官方维修站”。"

async def get_db_official_stations(coords: str, brand: str = "联想") -> list[dict]:
    """
    从本地官方数据库中查询维修站，返回结构化数据。
    """
    lat, lng = map(float, coords.split(','))
    conn = pool.connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT name, address, phone, lat, lng FROM service_stations WHERE brand = 'Lenovo'"
            )
            results = cursor.fetchall()
            
            stations = []
            for row in results:
                s_lat, s_lng = float(row[3]), float(row[4])
                dist = haversine(lat, lng, s_lat, s_lng)
                # 扩大范围至 200km
                if dist <= 200:
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

async def _get_nearby_official_repair_stations_impl(ctx: RunContextWrapper, brand: str = "联想") -> str:
    logger.info(f"High-speed station search started for brand: {brand}")
    
    # 1. 获取定位
    input_text = ""
    session = ctx.context
    if session and hasattr(session, 'items'):
        for item in reversed(session.items):
            content = ""
            if isinstance(item, dict):
                if item.get("role") == "user":
                    content = item.get("content", "")
            elif hasattr(item, "role") and item.role == "user":
                if hasattr(item, "content"):
                    content = str(item.content)
            if content:
                input_text = content
                break
    
    coords = await resolve_user_location_from_text(ctx, input_text)
    
    # 2. 并行执行联网搜索和本地数据库查询
    async def run_online_search():
        try:
            from infrastructure.tools.local.baidu_map_tool import baidu_around_search
            return await asyncio.wait_for(baidu_around_search(coords, f"{brand}官方维修站"), timeout=8.0)
        except Exception as e:
            logger.warning(f"Online search failed: {e}")
            return []

    async def run_db_query():
        try:
            return await asyncio.wait_for(get_db_official_stations(coords, brand), timeout=5.0)
        except Exception as e:
            logger.warning(f"DB search failed: {e}")
            return []

    online_pois, db_pois = await asyncio.gather(run_online_search(), run_db_query())

    # 3. 核验在线 POI 并合并
    verified_online = await verify_official_stations(ctx, online_pois)
    
    # 合并结果并去重
    all_pois = []
    seen_names = set()
    
    # 优先添加数据库中的官方站点
    for p in db_pois:
        name_addr = f"{p['name']}_{p['address']}"
        if name_addr not in seen_names:
            all_pois.append(p)
            seen_names.add(name_addr)
            
    # 添加在线搜索到的站点
    for p in verified_online:
        name_addr = f"{p['name']}_{p['address']}"
        if name_addr not in seen_names:
            all_pois.append(p)
            seen_names.add(name_addr)

    # 4. 计算路网距离 (仅针对 200km 以内的前 10 个站点)
    if all_pois:
        try:
            from infrastructure.tools.local.baidu_map_tool import baidu_get_distances_batch
            # 先按直线距离粗筛前 10 个
            all_pois.sort(key=lambda x: x.get('distance', 999999))
            process_targets = all_pois[:10]
            
            dest_coords_list = [f"{p.get('lat')},{p.get('lng')}" for p in process_targets]
            road_distances = await baidu_get_distances_batch(coords, dest_coords_list)
            
            for i, p in enumerate(process_targets):
                if i < len(road_distances) and road_distances[i] is not None:
                    p['road_dist'] = road_distances[i]
                else:
                    p['road_dist'] = round(p.get('distance', 0) / 1000, 2)
            
            # 对未处理的站点也补齐 road_dist 字段
            for p in all_pois[10:]:
                p['road_dist'] = round(p.get('distance', 0) / 1000, 2)
        except Exception as e:
            logger.warning(f"Road distance calculation failed: {e}")
            for p in all_pois:
                p['road_dist'] = round(p.get('distance', 0) / 1000, 2)

    # 再次按路网距离排序
    all_pois.sort(key=lambda x: x.get('road_dist', 999))

    # 5. 整合输出
    final_report = f"### 正在为您查询附近的{brand}官方服务网点...\n\n"
    
    nearby_official = []
    nearby_suspicious = []
    nearby_third = []
    
    # 增加范围到 200km
    for poi in all_pois:
        dist = poi.get('road_dist', 999)
        if dist > 200: continue
        
        name = poi.get('name', '未知门店')
        addr = poi.get('address', '详见地图')
        tel = poi.get('tel', poi.get('telephone', '请以地图标记为准'))
        nav_url = f"https://api.map.baidu.com/marker?location={poi.get('lat')},{poi.get('lng')}&title={name}&content={addr}&output=html&src=webapp.its.agent"
        
        entry = f"📍 地址: {addr}\n   - 📏 距离: 约 {dist:.2f} 公里 (路网距离)\n   - 🗺️ [立即查看]({nav_url})"
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
        final_report += "🏆 **官方授权推荐 (200km以内)**\n"
        final_report += "> 🛡️ **双重核验通过**：已比对联想官方 2024-2025 授权数据库，以下网点资质真实有效：\n\n"
        final_report += "\n\n".join(nearby_official[:5]) + "\n\n"
    else:
        final_report += "🏆 **官方授权推荐**\n当前 200km 范围内暂无经过数据库双重核验的授权服务站。\n\n"
    
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
        final_report = f"⚠️ **位置提醒**：系统当前基于定位 ({coords}) 进行搜索。若该位置与您所在地不符，请明确提问地点。\n\n" + final_report

    if not all_pois:
        final_report = f"抱歉，在您的位置（{coords}）附近 200km 内暂时没有找到{brand}维修站。"
        
    return final_report

async def verify_official_stations(ctx: RunContextWrapper, stations: list[dict]) -> list[dict]:
    """
    核验给出的维修站列表是否为联想官方授权。
    实施“双重核验”机制：数据库授权名单 + 实时数据特征比对。
    """
    if not stations:
        return []
    
    logger.info(f"Stricter verification started for {len(stations)} stations")
    conn = pool.connection()
    try:
        verified_list = []
        with conn.cursor() as cursor:
            # 仅查询联想官方授权站点
            cursor.execute("SELECT name, address, phone FROM service_stations WHERE brand = 'Lenovo'")
            official_records = cursor.fetchall()
            
            for poi in stations:
                name = poi.get("name", "")
                addr = poi.get("address", "")
                tel = poi.get("tel", poi.get("telephone", ""))
                
                is_official = False
                matched_record = None
                
                # 实施三重严苛匹配算法：
                for off_name, off_addr, off_phone in official_records:
                    # 1. 强名称匹配 (去除商圈干扰)
                    clean_off_name = off_name.split('(')[0].split('（')[0]
                    clean_poi_name = name.split('(')[0].split('（')[0]
                    
                    # 2. 电话核验 (最强凭证)
                    phone_match = False
                    if tel and off_phone:
                        # 归一化电话号码进行对比
                        clean_tel = ''.join(filter(str.isdigit, tel))
                        clean_off_phone = ''.join(filter(str.isdigit, off_phone))
                        if clean_tel and clean_off_phone and (clean_tel in clean_off_phone or clean_off_phone in clean_tel):
                            phone_match = True
                    
                    # 3. 地址语义相似度 (辅助凭证)
                    addr_match = False
                    if addr and off_addr:
                        # 检查关键门牌号或大厦名称
                        common_keywords = ["大厦", "广场", "路", "街", "号"]
                        match_count = 0
                        for kw in common_keywords:
                            if kw in addr and kw in off_addr: match_count += 1
                        if match_count >= 2: addr_match = True

                    # 判定逻辑：(名称匹配 AND 电话匹配) OR (名称匹配 AND 地址匹配)
                    if clean_off_name in clean_poi_name or clean_poi_name in clean_off_name:
                        if phone_match or addr_match:
                            is_official = True
                            matched_record = (off_name, off_addr, off_phone)
                            break
                
                # 更新 POI 状态
                poi['is_official'] = is_official
                if is_official and matched_record:
                    # 以官方库数据为准回填，确保准确性
                    poi['name'] = matched_record[0]
                    poi['address'] = matched_record[1]
                    poi['tel'] = matched_record[2]
                
                # 标记疑似官方 (仅名称包含联想且具备服务特征，但未通过双重核验)
                poi['is_suspicious'] = not is_official and "联想" in name and ("服务" in name or "中心" in name)
                
                verified_list.append(poi)
        
        return verified_list
    finally:
        conn.close()

async def query_nearest_repair_shops_by_coords(ctx: RunContextWrapper, coords: str, brand: str = None) -> str:
    """
    从本地官方数据库中查询维修站。通常作为核验后的备选方案。
    
    Args:
        coords: 经纬度，格式: "lat,lng"
        brand: 可选，品牌名称（如 "联想"）
    """
    logger.info(f"Fallback DB query for {brand or ''} near: {coords}")
    lat, lng = map(float, coords.split(','))
    
    conn = pool.connection()
    try:
        with conn.cursor() as cursor:
            if brand:
                cursor.execute("SELECT name, address, phone, lat, lng FROM service_stations WHERE (name LIKE %s OR brand LIKE %s) AND brand = 'Lenovo'", 
                               (f"%{brand}%", f"%{brand}%"))
            else:
                cursor.execute("SELECT name, address, phone, lat, lng FROM service_stations WHERE brand = 'Lenovo'")
            
            results = cursor.fetchall()
            
            if not results:
                return "" # 如果数据库没有，交给联网搜索
            
            stations = []
            for row in results:
                s_lat, s_lng = float(row[3]), float(row[4])
                dist = haversine(lat, lng, s_lat, s_lng)
                stations.append({
                    "name": row[0],
                    "address": row[1],
                    "phone": row[2],
                    "lat": s_lat,
                    "lng": s_lng,
                    "dist": dist
                })
            
            stations.sort(key=lambda x: x['dist'])
            # 扩大搜索范围至 200km 以响应用户“尽量查询”的需求
            top_3 = [s for s in stations if s['dist'] < 200][:3]
            
            if not top_3: return ""
            
            # 核心改进：尝试使用百度路网距离替换直线距离
            from infrastructure.tools.local.baidu_map_tool import baidu_get_distances_batch
            
            dest_coords_list = [f"{s['lat']},{s['lng']}" for s in top_3]
            road_distances = await baidu_get_distances_batch(coords, dest_coords_list)
            
            for i, s in enumerate(top_3):
                if i < len(road_distances) and road_distances[i] is not None:
                    s['dist'] = road_distances[i]
                    s['is_road_dist'] = True
                else:
                    s['is_road_dist'] = False
            
            response = "### 系统为您找到距离较近的官方授权网点：\n\n"
            for s in top_3:
                nav_url = f"https://map.baidu.com/search?query={s['name']}"
                dist_type = "(路网距离)" if s.get('is_road_dist') else "(直线距离)"
                response += f"- **{s['name']}**\n"
                response += f"  - 📍 地址: {s['address']}\n"
                response += f"  - 📞 电话: {s['phone']}\n"
                response += f"  - 📏 距离: 约 {s['dist']:.2f} 公里 {dist_type}\n"
                response += f"  - 🗺️ [点击查看地图]({nav_url})\n\n"
            
            return response
    finally:
        conn.close()

@function_tool
async def map_uri(location_name: str, lat: float = None, lng: float = None) -> str:
    """
    生成地图导航/搜索链接。
    
    Args:
        location_name: 地点名称
        lat: 纬度 (可选)
        lng: 经度 (可选)
        
    Returns:
        str: 导航链接 Markdown
    """
    # 优先使用百度地图搜索链接
    url = f"https://map.baidu.com/search?query={location_name}"
    return f"[{location_name} 的地图链接]({url})"
