"""Password hashing, JWT access tokens, opaque refresh tokens, CSRF and WS tickets."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Response
from redis.asyncio import Redis

from pianoforge.config import Settings

ACCESS_COOKIE = "pf_access"
REFRESH_COOKIE = "pf_refresh"
CSRF_COOKIE = "pf_csrf"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_PATH = "/api/v1/auth"

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
# Verified against when the email does not exist, so both paths cost the same.
_DUMMY_HASH = _hasher.hash("pianoforge-timing-equaliser")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return _hasher.verify(hashed or _DUMMY_HASH, password) and hashed is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# ------------------------------------------------------------------ access JWT
def create_access_token(user_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_s)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return uuid.UUID(str(payload["sub"]))
    except ValueError:
        return None


# --------------------------------------------------------------- refresh token
@dataclass(frozen=True)
class NewRefreshToken:
    token: str
    token_hash: bytes
    expires_at: datetime


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def new_refresh_token(settings: Settings) -> NewRefreshToken:
    token = secrets.token_urlsafe(32)
    return NewRefreshToken(
        token=token,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_s),
    )


# ---------------------------------------------------------------------- cookies
def set_session_cookies(
    response: Response, access: str, refresh: NewRefreshToken, settings: Settings
) -> str:
    csrf = secrets.token_urlsafe(24)

    def put(name: str, value: str, max_age: int, path: str, httponly: bool) -> None:
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            path=path,
            httponly=httponly,
            secure=settings.cookie_secure,
            domain=settings.cookie_domain,
            samesite="lax",
        )

    put(ACCESS_COOKIE, access, settings.access_token_ttl_s, "/", True)
    put(REFRESH_COOKIE, refresh.token, settings.refresh_token_ttl_s, REFRESH_PATH, True)
    # Readable by the web app, echoed in the X-CSRF-Token header (double submit).
    put(CSRF_COOKIE, csrf, settings.refresh_token_ttl_s, "/", False)
    return csrf


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, REFRESH_PATH), (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path, domain=settings.cookie_domain)


def csrf_matches(cookie: str | None, header: str | None) -> bool:
    return bool(cookie) and bool(header) and hmac.compare_digest(str(cookie), str(header))


# -------------------------------------------------------------------- WS ticket
def _ticket_key(ticket: str) -> str:
    return f"wst:{hashlib.sha256(ticket.encode()).hexdigest()}"


async def issue_ws_ticket(
    redis: Redis, user_id: uuid.UUID, job_id: uuid.UUID, settings: Settings
) -> str:
    ticket = secrets.token_urlsafe(24)
    await redis.set(
        _ticket_key(ticket),
        json.dumps({"user_id": str(user_id), "job_id": str(job_id)}),
        ex=settings.ws_ticket_ttl_s,
    )
    return ticket


async def redeem_ws_ticket(redis: Redis, ticket: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Single use: the ticket is deleted atomically on read."""
    raw = await redis.getdel(_ticket_key(ticket))
    if not raw:
        return None
    data = json.loads(raw)
    return uuid.UUID(data["user_id"]), uuid.UUID(data["job_id"])
