# 联想售后多智能体系统测试套件

本项目使用结构化的测试目录，以便于维护和扩展。

## 目录结构

- **`unit/`**: 存放单元测试。针对独立的函数或类，不依赖外部服务。
  - `test_html_converter.py`: HTML 转 Markdown 转换逻辑测试。
  - `test_string_utils.py`: 非法文件名字符处理测试。
- **`integration/`**: 存放集成测试。验证多个组件之间的交互或 API 接口。
  - `test_api.py`: 后端 API 接口测试。
  - `test_auth.py`: 身份认证逻辑测试。
  - `test_rag.py`: 检索增强生成 (RAG) 流程测试。
  - `test_mcp.py`: MCP 服务器连接与工具调用测试。
- **`playground/`**: 存放实验性脚本和库功能验证。不包含在自动化测试流程中。
  - `test_*_demo.py`: 各种基础库（jieba, bs4, async 等）的使用示例。

## 如何运行测试

确保已安装 `pytest`：
```bash
uv pip install pytest markdownify
```

运行所有测试：
```bash
pytest tests
```

仅运行单元测试：
```bash
pytest tests/unit
```

仅运行集成测试：
```bash
pytest tests/integration
```
