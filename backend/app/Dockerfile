FROM python:3.11-slim

WORKDIR /app

# 使用清华镜像源加速 apt
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null; \
    true

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件 (context 为 backend/, requirements 在 app/ 下)
COPY app/requirements.txt .

# 安装 Python 依赖 (清华 PyPI 镜像加速)
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn

# 复制主后端项目代码
COPY app/ .

# 复制共享 common 模块 (logger 等共享基础设施)
COPY common/ ./common/

# 暴露端口
EXPOSE 8002

# 启动命令 (uvicorn CLI, 容器内禁用开发模式的 reload)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
