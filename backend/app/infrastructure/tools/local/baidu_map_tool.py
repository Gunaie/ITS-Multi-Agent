import httpx
import asyncio
from typing import Optional, List, Dict, Any
from agents import RunContextWrapper
from config.settings import settings
from common.infrastructure.logging.logger import logger

# 创建全局共享的异步客户端，提高性能并复用连接
_client: Optional[httpx.AsyncClient] = None

def get_baidu_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        # 配置连接池：限制最大连接数，减少握手开销
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        _client = httpx.AsyncClient(timeout=10.0, limits=limits)
    return _client

async def baidu_geocode(address: str) -> str:
    """
    使用百度地图地理编码 API 将地址转换为经纬度 (BD-09 坐标系)
    """
    ak = settings.BAIDU_MAP_AK
    if not ak:
        logger.warning("Baidu Map AK is missing in settings")
        return ""
    
    url = "https://api.map.baidu.com/geocoding/v3/"
    params = {
        "ak": ak,
        "address": address,
        "output": "json"
    }
    
    try:
        client = get_baidu_client()
        logger.info(f"Baidu Geocoding request for: {address}")
        response = await client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 0:
                location = data["result"]["location"]
                coords = f"{location['lat']},{location['lng']}"
                logger.info(f"Baidu Geocoding success: {address} -> {coords}")
                return coords
            elif data.get("status") == 211:
                logger.error("百度地图 API 错误 (211): APP SN校验失败。请在百度地图控制台将该 AK 的校验方式改为“IP白名单”或“无校验”，或者提供 SK 密钥。")
                return ""
            elif data.get("status") == 302:
                logger.error(f"百度地图 API 错误 (status=302): 天配额超限。免费 AK 日配额约百余次，已超限。")
                return ""
            else:
                logger.warning(f"Baidu Geocoding API error: status={data.get('status')}, msg={data.get('msg')}")
    except Exception as e:
        logger.error(f"百度地理编码异常: {str(e)}")
    return ""

async def baidu_around_search(
    coords: str,
    keywords: str,
    radius: int = 50000,
    page_size: int = 20,
) -> List[Dict[str, Any]]:
    """
    使用百度地图地点检索 API 查询 POI (周边搜索)
    coords: "lat,lng" (BD-09)
    radius: 搜索半径（米），与展示口径保持一致
    page_size: 单页结果数（百度上限 20）
    """
    ak = settings.BAIDU_MAP_AK
    if not ak:
        return []
    
    url = "https://api.map.baidu.com/place/v2/search"
    params = {
        "ak": ak,
        "query": keywords,
        "location": coords, 
        "radius": radius,
        "output": "json",
        "page_size": min(page_size, 20),
        "scope": 2
    }
    
    try:
        client = get_baidu_client()
        logger.info(f"Baidu Place Search request at {coords} for: {keywords} (radius={radius}m)")
        response = await client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 0:
                pois = data.get("results", [])
                formatted_pois = []
                for poi in pois:
                    location = poi.get("location", {})
                    # distance 兼容两种返回位置：scope=2+location 时在 POI 顶层，
                    # 部分版本在 detail_info 内；都取不到时置 None（由调用方现算直线距离）
                    distance = poi.get("distance")
                    if distance is None:
                        distance = poi.get("detail_info", {}).get("distance")
                    formatted_pois.append({
                        "name": poi.get("name"),
                        "address": poi.get("address"),
                        "tel": poi.get("telephone"),
                        "lat": location.get("lat"),
                        "lng": location.get("lng"),
                        "distance": float(distance) if distance is not None else None
                    })
                logger.info(f"Baidu Place Search found {len(formatted_pois)} POIs")
                return formatted_pois
            elif data.get("status") == 211:
                logger.error("百度地图 API 错误 (211): APP SN校验失败。请在百度地图控制台将该 AK 的校验方式改为“IP白名单”或“无校验”，或者提供 SK 密钥。")
                return []
            elif data.get("status") == 302:
                logger.error(f"百度地图 API 错误 (status=302): {data.get('message', '天配额超限')}。免费 AK 日配额约百余次，已超限。service_agent 将退化到本地 DB 兜底查询。")
                return []
            else:
                logger.warning(f"百度 Place Search API error: status={data.get('status')}, msg={data.get('message')}")
    except Exception as e:
        logger.error(f"百度周边搜索异常: {str(e)}")
    return []

async def baidu_get_distance(origin: str, destination: str) -> Optional[float]:
    """
    使用百度地图批量算路 API (Route Matrix) 计算驾车路网距离 (公里)
    origin/destination: "lat,lng"
    """
    results = await baidu_get_distances_batch(origin, [destination])
    return results[0] if results else None

async def baidu_get_distances_batch(origin: str, destinations: List[str]) -> List[Optional[float]]:
    """
    批量计算路网距离
    destinations: ["lat,lng", "lat,lng", ...]
    """
    ak = settings.BAIDU_MAP_AK
    if not ak or not destinations:
        return [None] * len(destinations)
    
    url = "https://api.map.baidu.com/routematrix/v2/driving"
    # 百度 API 限制一次最多 50 个目的地
    dest_str = "|".join(destinations[:50])
    params = {
        "ak": ak,
        "origins": origin,
        "destinations": dest_str,
        "output": "json"
    }
    
    try:
        client = get_baidu_client()
        logger.info(f"Baidu Route Matrix batch request for {len(destinations)} points")
        response = await client.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 0:
                results = data.get("result", [])
                distances = []
                for res in results:
                    dist_m = res.get("distance", {}).get("value")
                    if dist_m is not None:
                        distances.append(round(dist_m / 1000, 2))
                    else:
                        distances.append(None)
                # 如果请求的 destinations 超过了 50 个，递归处理剩余的 (此处简单处理，仅取前 50)
                return distances
            elif data.get("status") == 211:
                logger.error("百度地图 API 错误 (211): APP SN校验失败。")
    except Exception as e:
        logger.error(f"百度批量距离计算异常: {str(e)}")
    
    return [None] * len(destinations)
