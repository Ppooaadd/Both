"""Fixed-window rate limiting on Redis (per user when authenticated, else per IP)."""

from __future__ import annotations

import time

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from pianoforge.api.errors import TooManyRequests
from pianoforge.logging import get_logger

log = get_logger(__name__)

_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


def client_ip(request: Request) -> str:
    # Behind the reverse proxy uvicorn runs with --proxy-headers, so this is the real client.
    return request.client.host if request.client else "unknown"


async def hit(redis: Redis, key: str, limit: int, window_s: int) -> tuple[bool, int]:
    """Returns (allowed, seconds_until_reset)."""
    bucket = int(time.time() // window_s)
    full_key = f"rl:{key}:{bucket}"
    try:
        count = int(await redis.eval(_SCRIPT, 1, full_key, str(window_s)))  # type: ignore[misc]
    except RedisError as exc:
        # Fail open: rate limiting must not take the API down with Redis.
        log.warning("ratelimit_unavailable", error=repr(exc))
        return True, 0
    reset = window_s - int(time.time() % window_s)
    return count <= limit, reset


async def enforce(redis: Redis, key: str, limit: int, window_s: int = 60) -> None:
    allowed, reset = await hit(redis, key, limit, window_s)
    if not allowed:
        raise TooManyRequests(
            "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(max(reset, 1))},
        )
