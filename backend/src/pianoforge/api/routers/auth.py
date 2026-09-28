"""Cookie-based sessions: short-lived JWT access + rotating opaque refresh tokens.

Refresh token reuse (a revoked token presented again) revokes the whole token
family, which logs out a thief and the victim alike and forces re-authentication.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime

import anyio
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from pianoforge.api.deps import CurrentUser, DbDep, SettingsDep, ip_rate_limit
from pianoforge.api.errors import Conflict, Unauthorized
from pianoforge.api.ratelimit import client_ip
from pianoforge.api.schemas import DeleteAccountIn, LoginIn, SessionOut, SignupIn, UserOut
from pianoforge.api.security import (
    REFRESH_COOKIE,
    clear_session_cookies,
    create_access_token,
    hash_password,
    hash_token,
    needs_rehash,
    new_refresh_token,
    set_session_cookies,
    verify_password,
)
from pianoforge.config import Settings
from pianoforge.db.models import AudioAsset, RefreshToken, User
from pianoforge.logging import get_logger
from pianoforge.worker.celery_app import celery_app

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _valid_ip(value: str) -> str | None:
    """``request.client.host`` is not always an IP (unix sockets, test clients)."""
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


_auth_limit = Depends(ip_rate_limit("auth", "auth_rate_limit_per_minute"))


async def _issue_session(
    db: DbDep,
    response: Response,
    request: Request,
    user: User,
    settings: Settings,
    family_id: uuid.UUID | None = None,
) -> SessionOut:
    refresh = new_refresh_token(settings)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh.token_hash,
            family_id=family_id or uuid.uuid4(),
            expires_at=refresh.expires_at,
            ip=_valid_ip(client_ip(request)),
            user_agent=(request.headers.get("user-agent") or "")[:512],
        )
    )
    await db.commit()
    access = create_access_token(user.id, settings)
    csrf = set_session_cookies(response, access, refresh, settings)
    return SessionOut(
        user=UserOut.model_validate(user),
        csrf_token=csrf,
        access_expires_in=settings.access_token_ttl_s,
        access_token=access,
    )


@router.post(
    "/signup",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_auth_limit],
)
async def signup(
    body: SignupIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> SessionOut:
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise Conflict("이미 가입된 이메일입니다.", code="email_taken") from e
    return await _issue_session(db, response, request, user, settings)


@router.post("/login", response_model=SessionOut, dependencies=[_auth_limit])
async def login(
    body: LoginIn, request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> SessionOut:
    user = (
        await db.execute(
            select(User).where(User.email == body.email.lower(), User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        raise Unauthorized("이메일 또는 비밀번호가 올바르지 않습니다.", code="invalid_credentials")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    return await _issue_session(db, response, request, user, settings)


@router.post("/refresh", response_model=SessionOut, dependencies=[_auth_limit])
async def refresh(
    request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> SessionOut:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise Unauthorized("로그인이 필요합니다.")
    token = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if token is None:
        clear_session_cookies(response, settings)
        raise Unauthorized("로그인이 필요합니다.")
    if token.revoked_at is not None:
        # Reuse of a rotated token: assume theft, kill the family.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        log.warning(
            "refresh_token_reuse", user_id=str(token.user_id), family_id=str(token.family_id)
        )
        raise Unauthorized("세션이 만료되었습니다. 다시 로그인해 주세요.", code="token_reuse")
    if token.expires_at <= now:
        raise Unauthorized("세션이 만료되었습니다. 다시 로그인해 주세요.", code="token_expired")
    user = await db.get(User, token.user_id)
    if user is None or user.deleted_at is not None:
        raise Unauthorized("로그인이 필요합니다.")
    token.revoked_at = now
    return await _issue_session(db, response, request, user, settings, family_id=token.family_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, db: DbDep, settings: SettingsDep, user: CurrentUser
) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw), RefreshToken.user_id == user.id)
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    body: DeleteAccountIn, response: Response, db: DbDep, settings: SettingsDep, user: CurrentUser
) -> Response:
    """Hard-delete the account; storage objects are removed asynchronously."""
    if not verify_password(body.password, user.password_hash):
        raise Unauthorized("비밀번호가 올바르지 않습니다.", code="invalid_credentials")
    asset_ids = [
        str(a)
        for a in (
            await db.execute(select(AudioAsset.id).where(AudioAsset.user_id == user.id))
        ).scalars()
    ]
    user_id = str(user.id)
    await db.delete(user)
    await db.commit()

    await anyio.to_thread.run_sync(
        lambda: celery_app.send_task(
            "pianoforge.maintenance.delete_user_data", args=[user_id, asset_ids]
        )
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_session_cookies(response, settings)
    return response
