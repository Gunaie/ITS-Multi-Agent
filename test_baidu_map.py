import asyncio
import os
import sys

# Add backend/app to path
sys.path.append(os.path.join(os.getcwd(), "backend", "app"))
sys.path.append(os.path.join(os.getcwd(), "backend"))

from infrastructure.tools.local.baidu_map_tool import baidu_geocode, baidu_around_search

async def test_baidu():
    print("Testing Baidu Geocoding...")
    address = "武汉工程大学流芳校区"
    coords = await baidu_geocode(address)
    print(f"Address: {address} -> Coords: {coords}")
    
    if coords:
        print(f"\nTesting Baidu Around Search near {coords}...")
        pois = await baidu_around_search(coords, "联想维修站")
        print(f"Found {len(pois)} POIs:")
        for poi in pois:
            print(f"- {poi['name']} | {poi['address']} | Dist: {poi['distance']}m")
    else:
        print("Geocoding failed, skipping search test.")

if __name__ == "__main__":
    asyncio.run(test_baidu())
