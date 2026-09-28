"""FastAPI application factory.

Run locally:
    uvicorn pianoforge.api.main:app --reload
Production (behind the reverse proxy):
    uvicorn pianoforge.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers \
        --forwarded-allow-ips='*' --workers 4
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.trustedhost import TrustedHostMiddleware

from pianoforge import __version__
from pianoforge.api.errors import install_error_handlers
from pianoforge.api.routers import arrangements, auth, health, jobs, projects, uploads, ws
from pianoforge.api.security import CSRF_HEADER
from pianoforge.config import Settings, get_settings
from pianoforge.db.session import get_async_engine
from pianoforge.logging import configure_logging, get_logger

log = get_logger("pianoforge.api")

# JSON bodies only; audio goes straight to object storage.
MAX_BODY_BYTES = 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.redis = Redis.from_url(
        settings.redis_url, decode_responses=True, health_check_interval=30
    )
    if settings.env == "dev":
        # Convenience for local runs; production buckets are provisioned by infra.
        import anyio

        from pianoforge.storage import get_storage

        try:
            await anyio.to_thread.run_sync(get_storage().ensure_bucket)
        except Exception as exc:
            log.warning("ensure_bucket_failed", error=repr(exc))
    log.info("api_started", version=__version__, env=settings.env)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await get_async_engine().dispose()


def _security_headers(settings: Settings) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        "Cross-Origin-Resource-Policy": "same-site",
    }
    if settings.is_prod:
        headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return headers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    app = FastAPI(
        title="PianoForge API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_prod else "/openapi.json",
    )
    app.state.settings = settings
    install_error_handlers(app)

    sec_headers = _security_headers(settings)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id")
        if not rid or len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex
        request.state.request_id = rid
        structlog.contextvars.bind_contextvars(request_id=rid)
        start = time.perf_counter()
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
                response: Response = JSONResponse(
                    {
                        "error": {
                            "code": "payload_too_large",
                            "message": "요청 본문이 너무 큽니다.",
                            "request_id": rid,
                        }
                    },
                    status_code=413,
                )
            else:
                response = await call_next(request)
            for k, v in sec_headers.items():
                response.headers.setdefault(k, v)
            response.headers["X-Request-ID"] = rid
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=round((time.perf_counter() - start) * 1000, 1),
                user_id=str(getattr(request.state, "user_id", "")) or None,
            )
            return response
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", CSRF_HEADER, "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    app.include_router(health.router)
    for r in (
        auth.router,
        uploads.router,
        projects.router,
        arrangements.router,
        jobs.router,
        ws.router,
    ):
        app.include_router(r, prefix=settings.api_prefix)
    app.include_router(ws.socket_router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("pianoforge.api.main:app", host="0.0.0.0", port=8000, proxy_headers=True)  # noqa: S104
