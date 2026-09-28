"""FastAPI dependencies: settings, DB, Redis, authentication, CSRF, rate limits."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pianoforge.api import ratelimit
from pianoforge.api.errors import Forbidden, Unauthorized
from pianoforge.api.security import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    csrf_matches,
    decode_access_token,
)
from pianoforge.config import Settings, get_settings
from pianoforge.db.models import User
from pianoforge.db.session import get_async_session
from pianoforge.storage import Storage, get_storage

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_async_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]
StorageDep = Annotated[Storage, Depends(get_storage)]


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token else None


async def current_user(request: Request, db: DbDep, settings: SettingsDep) -> User:
    token = _bearer(request)
    via = "bearer"
    if token is None:
        token = request.cookies.get(ACCESS_COOKIE)
        via = "cookie"
    if not token:
        raise Unauthorized("로그인이 필요합니다.")
    user_id = decode_access_token(token, settings)
    if user_id is None:
        raise Unauthorized("세션이 만료되었습니다. 다시 로그인해 주세요.", code="token_expired")
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise Unauthorized("로그인이 필요합니다.")

    # Cookie sessions are ambient credentials: unsafe methods need the CSRF token.
    if (
        via == "cookie"
        and request.method not in SAFE_METHODS
        and not csrf_matches(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER))
    ):
        raise Forbidden("CSRF 토큰이 올바르지 않습니다.", code="csrf_failed")
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def ip_rate_limit(
    scope: str, limit_attr: str = "rate_limit_per_minute"
) -> Callable[..., Awaitable[None]]:
    """Per-IP request budget per minute (anonymous endpoints: signup, login, refresh)."""

    async def _dep(request: Request, redis: RedisDep, settings: SettingsDep) -> None:
        key = f"{scope}:ip:{ratelimit.client_ip(request)}"
        await ratelimit.enforce(redis, key, int(getattr(settings, limit_attr)))

    return _dep


def user_rate_limit(
    scope: str, limit_attr: str = "rate_limit_per_minute"
) -> Callable[..., Awaitable[None]]:
    """Per-user request budget per minute (implies authentication)."""

    async def _dep(user: CurrentUser, redis: RedisDep, settings: SettingsDep) -> None:
        await ratelimit.enforce(redis, f"{scope}:u:{user.id}", int(getattr(settings, limit_attr)))

    return _dep
