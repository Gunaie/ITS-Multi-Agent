import asyncio
import os
import sys

# Add backend/app to path
sys.path.append(os.path.join(os.getcwd(), "backend", "app"))

from infrastructure.tools.mcp.mcp_servers import search_mac_client
from infrastructure.logging.logger import logger

async def test_mcp():
    print("Testing MCP connection...")
    try:
        await search_mac_client.connect()
        print("Successfully connected to MCP!")
        
        # List tools
        tools = await search_mac_client.list_tools()
        print(f"Available tools: {[t.name for t in tools]}")
        
    except Exception as e:
        print(f"Failed to connect to MCP: {e}")
    finally:
        await search_mac_client.cleanup()

if __name__ == "__main__":
    asyncio.run(test_mcp())
