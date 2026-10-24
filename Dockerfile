# Multi-stage lightweight build for Uzbekistan Legal RAG Platform
# Target: Linux VPS, 2 vCPU, 4GB RAM, Idle RAM < 350MB

FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir --user -r requirements.txt -c requirements.lock

# Final runtime image
FROM python:3.13-slim AS runner

WORKDIR /app

# Security: Non-root user
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --gid 1001 appuser

COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appgroup . .

# PYTHONUSERBASE: a system user made by `adduser --system` has HOME=/nonexistent, so without it Python looked for the
# packages in /nonexistent/.local and the container died at start with "No module named 'uvicorn'".
ENV MALLOC_ARENA_MAX=2 MALLOC_MMAP_THRESHOLD_=65536 \
    PYTHONUSERBASE=/home/appuser/.local \
    PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STORAGE_DIR=/app/data/store \
    CACHE_DB_PATH=/app/data/cache/query_cache.db

USER appuser

# Behind a reverse proxy the rate limiter must see the visitor, not the proxy: set TRUSTED_PROXIES=1 in .env (one proxy that
# appends X-Forwarded-For). uvicorn itself trusts forwarded headers only from FORWARDED_ALLOW_IPS (default 127.0.0.1), and a
# proxy outside the container is never 127.0.0.1. Use one of the two mechanisms, not both.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import httpx; r = httpx.get('http://127.0.0.1:8000/health'); exit(0 if r.status_code == 200 else 1)"

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
