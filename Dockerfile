# Multi-stage lightweight build for Uzbekistan Legal RAG Platform
# Target: Linux VPS, 2 vCPU, 4GB RAM, Idle RAM < 350MB

FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final runtime image
FROM python:3.13-slim AS runner

WORKDIR /app

# Security: Non-root user
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --gid 1001 appuser

COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appgroup . .

ENV MALLOC_ARENA_MAX=2 MALLOC_MMAP_THRESHOLD_=65536 \
    PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STORAGE_DIR=/app/data/store \
    CACHE_DB_PATH=/app/data/cache/query_cache.db

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import httpx; r = httpx.get('http://127.0.0.1:8000/health'); exit(0 if r.status_code == 200 else 1)"

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
