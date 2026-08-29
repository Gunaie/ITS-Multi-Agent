
import httpx
from agents import RunContextWrapper
from config.settings import settings
from common.infrastructure.logging.logger import logger

async def amap_geocode(address: str) -> str:
    """
    使用高德地图地理编码 API 将地址转换为经纬度
    """
    api_key = settings.AMAP_API_KEY
    if not api_key:
        return ""
    
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": api_key,
        "address": address
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "1" and data.get("geocodes"):
                    location = data["geocodes"][0]["location"] # "lng,lat"
                    lng, lat = location.split(",")
                    return f"{lat},{lng}"
    except Exception as e:
        logger.error(f"高德地理编码失败: {e}")
    return ""

async def amap_around_search(coords: str, keywords: str, radius: int = 50000) -> list:
    """
    使用高德地图周边搜索 API 查询 POI
    coords: "lat,lng"
    """
    api_key = settings.AMAP_API_KEY
    if not api_key:
        return []
    
    lat, lng = coords.split(",")
    url = "https://restapi.amap.com/v3/place/around"
    params = {
        "key": api_key,
        "location": f"{lng},{lat}", # 高德 API 要求 lng,lat
        "keywords": keywords,
        "radius": radius,
        "offset": 10,
        "page": 1,
        "extensions": "all"
    }
    
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "1":
                    return data.get("pois", [])
    except Exception as e:
        logger.error(f"高德周边搜索失败: {e}")
    return []

async def bailian_amap_search(ctx: RunContextWrapper, query: str) -> str:
    """
    兼容原有的百炼接口定义，但内部切换为官方 API 以提高稳定性
    """
    api_key = settings.AMAP_API_KEY
    if not api_key:
        return "未配置 AMAP_API_KEY，请在 .env 文件中设置。"
    
    # 如果 query 看起来像是在搜坐标
    if "坐标" in query or "经纬度" in query:
        address = query.replace("的精确经纬度坐标", "").replace("经纬度坐标", "").strip()
        coords = await amap_geocode(address)
        if coords:
            return f"地址 {address} 的坐标为: {coords}"
    
    # 普通周边搜索
    session = ctx.context
    location = "30.5928,114.3055" # 默认武汉
    if session and hasattr(session, 'context'):
        location = session.context.get("user_location", location)
    
    pois = await amap_around_search(location, query)
    if not pois:
        return f"在高德地图中未找到与 '{query}' 相关的结果。"
    
    results = []
    for poi in pois[:5]:
        name = poi.get("name")
        address = poi.get("address")
        dist = poi.get("distance")
        tel = poi.get("tel")
        results.append(f"- {name}\n  地址: {address}\n  电话: {tel}\n  距离: {dist}米")
    
    return "【高德地图实时数据】\n" + "\n".join(results)
