import json
import math
import asyncio
import time
from infrastructure.database.database_pool import pool
from agents import function_tool, RunContextWrapper
from agents.memory import Session
from common.infrastructure.logging.logger import logger

def haversine(lat1, lon1, lat2, lon2):
    """计算两个经纬度之间的距离（公里）"""
    R = 6371  # 地球半径
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

async def resolve_user_location_from_text(ctx: RunContextWrapper, text: str) -> str:
    """
    从用户文本中解析出经纬度坐标，或从会话上下文中获取。
    返回格式: "lat,lng"
    """
    session = ctx.context
    city_coords = {
        "武汉": "30.5928,114.3055",
        "流芳校区": "30.4578,114.4358", # 针对用户常测的地标进行硬编码加速
        "光谷": "30.5065,114.3942",
        "上海": "31.2304,121.4737",
        "广州": "23.1291,113.2644",
        "深圳": "22.5431,114.0579",
        "杭州": "30.2741,120.1551",
        "南京": "32.0603,118.7969",
        "成都": "30.5728,104.0668",
        "北京": "39.9042,116.4074"
    }
    
    # 0. 强匹配：按关键词长度降序排列，优先匹配长词（如“流芳校区”优于“武汉”）
    sorted_keys = sorted(city_coords.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in text:
            coords = city_coords[key]
            logger.info(f"Strong match detected: '{key}' in text, using coordinates: {coords}")
            if session and hasattr(session, 'context'):
                session.context["user_location"] = coords
            return coords

    # 1. 优先从会话上下文中获取（前端传来的实时位置）
    if session and hasattr(session, 'context'):
        cached_loc = session.context.get("user_location")
        # 只有当用户没有提到任何地点相关词汇时，才沿用之前的缓存
        if cached_loc and len(text) < 5:
            logger.info(f"Using cached location for short query: {cached_loc}")
            return cached_loc
    
    # 2. 智能解析：如果文本包含具体地标（如“武汉工程大学”），使用地图工具解析经纬度
    if len(text) > 2:
        try:
            from infrastructure.tools.local.amap_tool import bailian_amap_search
            logger.info(f"Attempting smart location resolution for: {text}")
            # 这里的超时设短一点，如果解析不了就快速回退
            search_res = await asyncio.wait_for(
                bailian_amap_search(ctx, f"{text} 的精确经纬度坐标"),
                timeout=5.0
            )
            import re
            # 改进正则，匹配多种坐标格式，如 "30.4578, 114.4358" 或 "纬度：30.4578，经度：114.4358"
            matches = re.findall(r"(\d+\.\d+)\s*[,，\s]\s*(\d+\.\d+)", search_res)
            if matches:
                lat, lng = matches[0]
                coords = f"{lat},{lng}"
                logger.info(f"Smart resolution success: {coords}")
                if session and hasattr(session, 'context'):
                    session.context["user_location"] = coords
                return coords
        except Exception as e:
            logger.warning(f"Smart location resolution failed: {e}")

    # 3. 兜底逻辑：如果之前有缓存则用缓存，否则用北京
    if session and hasattr(session, 'context') and session.context.get("user_location"):
        return session.context["user_location"]
        
    logger.warning("No location info found. Falling back to default center (Beijing).")
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
        return f"查询{brand}维修站服务响应超时。建议您直接在高德地图中搜索“{brand}官方维修站”。"

async def _get_nearby_official_repair_stations_impl(ctx: RunContextWrapper, brand: str = "联想") -> str:
    logger.info(f"High-speed station search started for brand: {brand}")
    
    # 1. 获取定位 - 改进：从会话历史中寻找最后一条用户消息
    input_text = ""
    session = ctx.context
    if session and hasattr(session, 'items'):
        # 逆序查找最后一条用户消息
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
    
    # 核心优化点：获取坐标后，并行执行联网搜索和本地数据库查询
    coords = await resolve_user_location_from_text(ctx, input_text)
    
    from infrastructure.tools.local.amap_tool import bailian_amap_search
    
    # 定义并行任务
    async def run_online_search():
        try:
            start_time = time.time()
            logger.info(f"Parallel Task: Online map probe started...")
            map_text = await asyncio.wait_for(
                bailian_amap_search(ctx, f"{brand}官方维修站"), 
                timeout=8.0 # 稍微放宽一点并行超时
            )
            logger.info(f"Online map probe finished in {time.time() - start_time:.2f}s")
            
            import re
            names = re.findall(r"[\d]+\.\s*([^\n]+)", map_text)
            if not names:
                names = re.findall(r"\*\*([^*]+)\*\*", map_text)
            return names[:5]
        except Exception as e:
            logger.warning(f"Online probe task failed: {e}")
            return []

    async def run_db_query():
        try:
            start_time = time.time()
            logger.info(f"Parallel Task: Local DB query started...")
            db_res = await asyncio.wait_for(
                query_nearest_repair_shops_by_coords(ctx, coords, brand),
                timeout=4.0
            )
            logger.info(f"Local DB query finished in {time.time() - start_time:.2f}s")
            return db_res
        except Exception as e:
            logger.warning(f"DB query task failed: {e}")
            return ""

    # 并行执行
    logger.info("Executing Online Search and DB Query in parallel...")
    online_names, db_results = await asyncio.gather(
        run_online_search(),
        run_db_query()
    )

    # 3. 官方核验 (仅对联网搜索结果进行核验)
    verification_text = ""
    if online_names:
        try:
            verification_text = await asyncio.wait_for(
                verify_official_stations(ctx, online_names),
                timeout=5.0
            )
        except Exception as e:
            logger.warning(f"Verification task failed: {e}")
    
    # 5. 整合输出
    final_report = f"### 正在为您查询附近的{brand}官方服务网点...\n\n"
    
    # 距离预警逻辑：如果最近的网点超过 30km，说明定位可能与目标区域不符
    min_dist = 999
    if db_results and "距离: 约" in db_results:
        import re
        dists = re.findall(r"距离: 约 ([\d\.]+) 公里", db_results)
        if dists:
            min_dist = min(float(d) for d in dists)
    
    source_info = []
    if online_names: source_info.append("实时地图搜索")
    if db_results: source_info.append("本地官方核验库")
        
    if source_info:
        final_report += f"> 数据来源：{', '.join(source_info)}\n\n"

    if min_dist > 30 and min_dist != 999:
        final_report += f"⚠️ **提醒**：系统检测到您当前定位（{coords}）距离这些网点较远（约 {min_dist:.1f}km）。如果您是在其他城市查询，请在提问中包含具体地点（如“在光谷附近”）。\n\n"

    if verification_text:
        final_report += verification_text + "\n\n"
    
    # 仅当实时结果不足或为了增强核验时，才显示数据库结果
    if db_results and (not online_names or len(online_names) < 2):
        final_report += db_results
        
    if not verification_text and not db_results:
        final_report = f"抱歉，在您的位置（{coords}）附近暂时没有找到经官方核验的{brand}维修站。建议您通过高德地图搜索“{brand}官方维修站”并认准授权标识。"
        
    return final_report

async def verify_official_stations(ctx: RunContextWrapper, station_names: list[str]) -> str:
    """
    核验给出的维修站列表是否为联想官方授权。
    
    Args:
        station_names: 需要核验的维修站名称列表
    """
    if not station_names:
        return "未提供待核验的维修站名称。"
    
    logger.info(f"Verifying official status for: {station_names}")
    conn = pool.connection()
    try:
        results = []
        with conn.cursor() as cursor:
            for name in station_names:
                # 模糊匹配名称，确保包含品牌关键词且匹配度高
                cursor.execute("SELECT name, address, phone FROM service_stations WHERE name LIKE %s AND brand = 'Lenovo'", 
                               (f"%{name}%",))
                match = cursor.fetchone()
                if match:
                    results.append(f"✅ **{name}** (官方授权店)\n   - 官方地址: {match[1]}\n   - 官方电话: {match[2]}")
                else:
                    results.append(f"⚠️ **{name}** (未在官方授权名单中，建议核实)")
        
        if not results:
            return "本地官方数据库中未找到上述网点的授权记录。建议优先认准招牌包含“联想授权服务中心”字样的门店。"
            
        return "### 官方授权核验结果：\n\n" + "\n\n".join(results)
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
            top_3 = [s for s in stations if s['dist'] < 200]
            
            if not top_3: return ""
            
            response = "### 系统为您找到距离较近的官方授权网点：\n\n"
            for s in top_3:
                nav_url = f"https://www.amap.com/search?query={s['name']}"
                response += f"- **{s['name']}**\n"
                response += f"  - 📍 地址: {s['address']}\n"
                response += f"  - 📞 电话: {s['phone']}\n"
                response += f"  - 📏 距离: 约 {s['dist']:.2f} 公里\n"
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
    # 优先使用高德地图搜索链接
    url = f"https://www.amap.com/search?query={location_name}"
    return f"[{location_name} 的地图链接]({url})"
