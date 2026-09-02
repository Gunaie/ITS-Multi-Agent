FROM python:3.11-slim-bookworm

WORKDIR /app

# 注：清华/国内 debian 镜像偶发 403 Forbidden，故此处不执行 sed 换源，
# 直接使用官方 deb.debian.org（稳定可访问，只慢几秒）。
# PyPI 安装阶段仍使用清华 pypi.tuna 加速，见下方 pip install。

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件 (context 为 backend/, requirements 在 app/ 下)
COPY app/requirements.txt .

# 安装 Python 依赖
# 注：清华 pypi.tuna 今日出现 403 / versions: none 全站异常，
# 故改为使用官方 PyPI 主源 + 阿里镜像作为额外索引（双源互为兜底），
# 并显式开启超时/重试/优先二进制 wheel，避免构建因单点网络卡死。
RUN pip install \
        --no-cache-dir \
        --prefer-binary \
        --timeout 120 \
        --retries 3 \
        --index-url https://pypi.org/simple/ \
        --extra-index-url https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com \
        -r requirements.txt

# 复制主后端项目代码
COPY app/ .

# 复制共享 common 模块 (logger 等共享基础设施)
COPY common/ ./common/

# 暴露端口
EXPOSE 8002

# 启动命令 (uvicorn CLI, 容器内禁用开发模式的 reload)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
