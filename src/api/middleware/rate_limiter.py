import time
from collections import defaultdict
from typing import Dict, List
from fastapi import Request, HTTPException
from src.config import settings


class TokenBucketRateLimiter:
    """Sliding-window in-memory rate limiter per IP address with zero external daemon."""

    def __init__(self, requests_per_minute: int = 60):
        self.limit = requests_per_minute
        self.window = 60.0  # seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def check(self, request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        
        # Clean timestamps older than window
        timestamps = [t for t in self.requests[client_ip] if now - t < self.window]
        self.requests[client_ip] = timestamps

        if len(timestamps) >= self.limit:
            raise HTTPException(
                status_code=429,
                detail="So'rovlar soni me'yordan oshib ketdi. Iltimos, birozdan so'ng qayta urinib ko'ring (Rate limit exceeded)."
            )

        self.requests[client_ip].append(now)


rate_limiter = TokenBucketRateLimiter(settings.RATE_LIMIT_PER_MINUTE)
