"""Per-process rate limit; production edge proxy should add distributed protections."""
from collections import defaultdict, deque
import time
from threading import Lock
from fastapi import HTTPException, Request
from app.core.config import settings

_lock = Lock()
_calls: dict[str, deque[float]] = defaultdict(deque)


def check_rate(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _lock:
        q = _calls[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings().api_rate_limit_per_minute:
            raise HTTPException(429, "Rate limit exceeded. Retry after one minute.", headers={"Retry-After": "60"})
        q.append(now)
        if len(_calls) > 2000:
            for key in list(_calls):
                if not _calls[key] or now - _calls[key][-1] > 60:
                    del _calls[key]
