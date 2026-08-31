"""
端到端冒烟测试: 直接调用维修站检索工具实现（绕过 function_tool 包装）
- 使用真实百度地图 API 与 MySQL（服务不可用时工具应优雅降级）
- 运行: 在 backend/app 目录下执行
"""
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, _APP_DIR)
sys.path.insert(0, _BACKEND_DIR)

from infrastructure.tools.local.service_station import (
    _get_nearby_official_repair_stations_impl,
)


class FakeSession:
    """模拟 SimpleSession 的 context 属性"""
    def __init__(self, ctx: dict):
        self._ctx = dict(ctx)

    @property
    def context(self) -> dict:
        return self._ctx


class FakeCtx:
    """模拟 RunContextWrapper（impl 仅使用 ctx.context）"""
    def __init__(self, context):
        self.context = context


async def main():
    # 场景1: location_hint 指定"武汉光谷"（走 geocode 路径）
    print("=" * 70)
    print("场景1: 用户说 '我在武汉光谷附近找维修站' (hint=武汉光谷)")
    ctx = FakeCtx(FakeSession({"client_ip": ""}))
    report = await _get_nearby_official_repair_stations_impl(ctx, "联想", "武汉光谷")
    print(report[:1500])

    # 场景2: 无 hint、无缓存、私网 IP -> 应返回追问提示
    print("=" * 70)
    print("场景2: 无任何定位线索 (应追问用户)")
    ctx2 = FakeCtx(FakeSession({"client_ip": "192.168.1.5"}))
    report2 = await _get_nearby_official_repair_stations_impl(ctx2, "联想", "")
    print(report2)
    assert "无法确定用户位置" in report2, "场景2应返回追问提示"

    # 场景3: 会话缓存有效 (GPS 记录) -> 直接使用缓存
    print("=" * 70)
    print("场景3: 前端 GPS 缓存 (武汉坐标)")
    import time as _t
    ctx3 = FakeCtx(FakeSession({
        "location_record": {"coords": "30.5928,114.3055", "source": "frontend_gps",
                            "display": "", "ts": _t.time()},
        "client_ip": "",
    }))
    report3 = await _get_nearby_official_repair_stations_impl(ctx3, "联想", "")
    print(report3[:1200])

    print("=" * 70)
    print("SMOKE TEST DONE")


if __name__ == "__main__":
    asyncio.run(main())
