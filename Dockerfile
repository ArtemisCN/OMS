# ============================================================
# 医院IT工单系统 — Docker 镜像
# 基于 python:3.12-slim，非 root 运行，healthcheck 三件套
# 数据卷：/app/instance（SQLite）、/app/uploads、/app/.secret
# ============================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 系统依赖（Pillow 编译 + cron sidecar 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libjpeg-dev \
        zlib1g-dev \
        cron \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建运行目录 + 非 root 用户
RUN mkdir -p /app/instance /app/uploads /app/logs \
    && useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

# 健康检查（三件套：/health /health/readiness /health/liveness）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3)" || exit 1

EXPOSE 5000

# gunicorn 3 worker（与 systemd 生产一致）
CMD ["gunicorn", "-w", "3", "--preload", "-b", "0.0.0.0:5000", "--max-requests=10000", "--max-requests-jitter=2000", "--timeout=60", "wsgi:app"]
