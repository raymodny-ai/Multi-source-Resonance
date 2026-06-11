# =============================================================================
# 多源共振监控系统 - Docker 多阶段构建
# =============================================================================
# 阶段 1: 前端构建 (Node.js)
FROM node:22-alpine AS frontend-builder

WORKDIR /app/frontend

# 利用 Docker 缓存层: 先复制依赖文件
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps

# 复制前端源码并构建
COPY frontend/ ./
RUN npm run build

# =============================================================================
# 阶段 2: Python 运行环境
FROM python:3.12-slim

LABEL maintainer="Multi-source Resonance Team"
LABEL description="多源共振暗盘与流动性微观结构盘中自动监控系统"

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# 安装 Python 依赖 (利用缓存层)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY --chown=appuser:appuser . .

# 复制前端构建产物
COPY --from=frontend-builder --chown=appuser:appuser /app/frontend/dist ./frontend/dist

# 创建运行时目录并设置权限
RUN mkdir -p /app/logs /app/database /app/data /app/reports && \
    chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8524/api/health || exit 1

# 暴露端口
EXPOSE 8524

# 启动命令
CMD ["python", "api_server.py"]
