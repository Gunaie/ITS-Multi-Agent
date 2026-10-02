"""
pytest 全局引导:
1. 将 backend/app 与 backend 注入 sys.path, 使测试可直接 import
   infrastructure / multi_agent / common 等包 (无需安装为 site-package);
2. collect_ignore: 排除需真实百炼 API 的手动验证脚本,
   它们仍可通过 `python <script>.py` 独立运行, 但不进入 pytest 收集。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.normpath(os.path.join(_HERE, "..", "app"))
_BACKEND_DIR = os.path.normpath(os.path.join(_HERE, ".."))
for _p in (_APP_DIR, _BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# test_model_compat.py 内的 async def test_basic_chat/test_tool_call 是
# 供其 main() 调用的辅助协程 (需要真实 API key), 不是 pytest 用例
collect_ignore = ["test_model_compat.py"]
