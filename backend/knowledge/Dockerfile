FROM python:3.11-slim

WORKDIR /app

# 使用清华镜像源加速 apt (Debian trixie)
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list 2>/dev/null; \
    true

# 安装系统依赖 (极简: 仅 libmagic 用于文件类型检测, PDF/DOCX 解析走纯 Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmagic-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件 (context 为 backend/, requirements 在 knowledge/ 下)
COPY knowledge/requirements.txt .

# 安装 Python 依赖 (清华 PyPI 镜像加速)
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn

# 复制知识库项目代码
COPY knowledge/ .

# 复制共享 common 模块 (settings 等共享配置)
COPY common/ ./common/

# 暴露端口
EXPOSE 8001

# 启动命令 (容器内必须绑定 0.0.0.0, 否则端口映射失效; 开发模式的 host=127.0.0.1+reload 不可用于容器)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
