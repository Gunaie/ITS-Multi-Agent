import json
import math
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

@function_tool
async def resolve_user_location_from_text(ctx: RunContextWrapper, text: str) -> str:
    """
    从用户文本中解析出经纬度坐标，或从会话上下文中获取。
    返回格式: "lat,lng"
    """
    session = ctx.context
    city_coords = {
        "武汉": "30.5928,114.3055",
        "上海": "31.2304,121.4737",
        "广州": "23.1291,113.2644",
        "深圳": "22.5431,114.0579",
        "杭州": "30.2741,120.1551",
        "南京": "32.0603,118.7969",
        "成都": "30.5728,104.0668",
        "北京": "39.9042,116.4074"
    }
    
    # 1. 优先从会话上下文中获取（前端传来的位置）
    if session and hasattr(session, 'context') and session.context.get("user_location"):
        loc = session.context["user_location"]
        # 如果是坐标格式 "lat,lng"，直接返回
        if "," in loc and all(c.isdigit() or c == "." or c == "-" for c in loc.replace(",", "")):
            logger.info(f"Using coordinates from session context: {loc}")
            return loc
        # 如果是城市名，尝试转换
        for city, coords in city_coords.items():
            if city in loc:
                logger.info(f"Resolved city '{loc}' from context to coordinates: {coords}")
                return coords
    
    # 2. 尝试从提问文本中解析地点信息
    for city, coords in city_coords.items():
        if city in text:
            logger.info(f"Detected city '{city}' in text, using coordinates: {coords}")
            return coords

    # 3. 兜底逻辑
    logger.warning("No location info found. Falling back to default center (Beijing).")
    return "39.9042,116.4074"

@function_tool
async def query_nearest_repair_shops_by_coords(ctx: RunContextWrapper, coords: str, brand: str = None) -> str:
    """
    根据经纬度查询最近的维修站。
    
    Args:
        coords: 经纬度，格式: "lat,lng"
        brand: 可选，品牌名称（如 "联想", "小米", "华为"），用于过滤结果
    """
    logger.info(f"Querying {brand or ''} repair shops near: {coords}")
    lat, lng = map(float, coords.split(','))
    
    # 检查是否是默认坐标
    is_default = (coords == "39.9042,116.4074")
    
    conn = pool.connection()
    try:
        with conn.cursor() as cursor:
            if brand:
                # 简单的模糊匹配
                cursor.execute("SELECT name, address, phone, lat, lng FROM service_stations WHERE name LIKE %s OR brand LIKE %s", 
                               (f"%{brand}%", f"%{brand}%"))
            else:
                cursor.execute("SELECT name, address, phone, lat, lng FROM service_stations")
            
            results = cursor.fetchall()
            
            if not results:
                return f"本地数据库中未找到附近的 {brand or ''} 维修站信息。建议使用高德地图工具进行在线搜索。"
            
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
            # 距离阈值设定
            top_3 = [s for s in stations if s['dist'] < 100]
            
            if not top_3:
                return f"在您的位置附近 100km 内未找到本地记录的 {brand or ''} 维修站。建议使用高德地图在线搜索。"
            
            response = ""
            if is_default:
                response += f"⚠️ **提示**：未获取到您的精确位置，已为您推荐北京市中心附近的 {brand or ''} 维修站：\n\n"
            else:
                response += f"为您找到距离您约 {stations[0]['dist']:.2f}km 起的 {brand or ''} 维修站：\n\n"

            for s in top_3:
                # 生成带坐标的真实高德导航链接
                # 格式：https://uri.amap.com/marker?position=lng,lat&name=名称
                nav_url = f"https://uri.amap.com/marker?position={s['lng']},{s['lat']}&name={s['name']}"
                response += f"### {s['name']}\n"
                response += f"- **地址** ：{s['address']}\n"
                response += f"- **电话** ：{s['phone']}\n"
                response += f"- **距离** ：{s['dist']:.2f}公里\n"
                response += f"- **导航** ：[点击前往高德地图查看路线]({nav_url})\n\n"
            
            if is_default:
                response += "注：如需更精准的距离计算，请允许浏览器获取您的位置信息。"
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
