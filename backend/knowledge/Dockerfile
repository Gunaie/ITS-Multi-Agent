FROM python:3.11-slim-bookworm

WORKDIR /app

# 注：清华 debian 镜像偶发 403，不做 apt 换源，使用官方 deb.debian.org
# PyPI 安装阶段仍使用清华 pypi.tuna 加速。

# 安装系统依赖 (极简: 仅 libmagic 用于文件类型检测, PDF/DOCX 解析走纯 Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmagic-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件 (context 为 backend/, requirements 在 knowledge/ 下)
COPY knowledge/requirements.txt .

# 安装 Python 依赖（双源兜底：官方 PyPI + 阿里云镜像；今天清华 pypi.tuna 全站 403/versions none 不可用）
RUN pip install \
        --no-cache-dir \
        --prefer-binary \
        --timeout 120 \
        --retries 3 \
        --index-url https://pypi.org/simple/ \
        --extra-index-url https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com \
        -r requirements.txt

# 复制知识库项目代码
COPY knowledge/ .

# 复制共享 common 模块 (settings 等共享配置)
COPY common/ ./common/

# 暴露端口
EXPOSE 8001

# 启动命令 (容器内必须绑定 0.0.0.0, 否则端口映射失效; 开发模式的 host=127.0.0.1+reload 不可用于容器)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
