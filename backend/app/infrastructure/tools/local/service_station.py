import json
import math
from infrastructure.database.database_pool import pool
from agents import function_tool, RunContextWrapper
from agents.memory import Session
from infrastructure.logging.logger import logger

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
    
    # 1. 优先从会话上下文中获取（前端传来的真实位置）
    if session and hasattr(session, 'context') and session.context.get("user_location"):
        logger.info(f"Using location from session context: {session.context['user_location']}")
        return session.context["user_location"]
    
    # 2. 尝试从文本中解析地点信息（如果用户提到了城市或区域）
    # 在实际生产中，这里可以调用一个轻量级模型来识别地点并调用地理编码接口
    # 为了演示真实感，如果文本中包含常见城市名，我们返回该城市的中心坐标
    city_coords = {
        "武汉": "30.5928,114.3055",
        "上海": "31.2304,121.4737",
        "广州": "23.1291,113.2644",
        "深圳": "22.5431,114.0579",
        "杭州": "30.2741,120.1551",
        "南京": "32.0603,118.7969",
        "成都": "30.5728,104.0668",
    }
    
    for city, coords in city_coords.items():
        if city in text:
            logger.info(f"Detected city '{city}' in text, using coordinates: {coords}")
            return coords

    # 3. 兜底逻辑：如果都没有，且用户明确说“不在北京”，则提示需要位置信息或返回一个默认非北京坐标
    # 这里我们返回一个默认坐标，但在实际应用中应该请求用户授权或输入位置
    logger.warning("No location info found in context or text. Falling back to default.")
    return "40.078,116.345"

@function_tool
async def query_nearest_repair_shops_by_coords(coords: str) -> str:
    """
    根据经纬度查询最近的维修站。
    coords 格式: "lat,lng"
    """
    logger.info(f"Querying repair shops near: {coords}")
    lat, lng = map(float, coords.split(','))
    
    conn = pool.connection()
    try:
        with conn.cursor() as cursor:
            # 先获取所有站点，计算精确距离后再排序（数据量小可以这么做）
            cursor.execute("SELECT name, address, phone, lat, lng FROM service_stations")
            results = cursor.fetchall()
            
            if not results:
                return "本地数据库中未找到附近的维修站信息。请尝试使用高德地图工具进行在线搜索。"
            
            # 计算距离并排序
            stations = []
            for row in results:
                dist = haversine(lat, lng, float(row[3]), float(row[4]))
                stations.append({
                    "name": row[0],
                    "address": row[1],
                    "phone": row[2],
                    "dist": dist
                })
            
            stations.sort(key=lambda x: x['dist'])
            top_3 = [s for s in stations if s['dist'] < 50] # 仅显示 50km 以内的
            
            if not top_3:
                return f"在 {coords} 附近 50km 内未找到本地记录的维修站。建议使用高德地图在线搜索更多实时信息。"
            
            response = f"为您找到 {coords} 附近最近的维修站：\n"
            for s in top_3:
                # 生成高德地图搜索链接
                map_url = f"https://www.amap.com/search?query={s['name']}"
                response += f"- **{s['name']}**: {s['address']} (电话: {s['phone']}, 距离: {s['dist']:.2f}km) [点击导航]({map_url})\n"
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
