from __future__ import annotations

import asyncio

import anyio
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from pianoforge import __version__
from pianoforge.api.deps import DbDep, RedisDep, StorageDep

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_S = 3.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is serving requests."""
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
async def readyz(db: DbDep, redis: RedisDep, storage: StorageDep) -> JSONResponse:
    """Readiness: all backing services reachable."""

    async def check_db() -> None:
        await db.execute(text("SELECT 1"))

    async def check_redis() -> None:
        await redis.ping()

    async def check_s3() -> None:
        await anyio.to_thread.run_sync(storage.ping)

    results: dict[str, str] = {}
    for name, fn in (("database", check_db), ("redis", check_redis), ("storage", check_s3)):
        try:
            await asyncio.wait_for(fn(), timeout=CHECK_TIMEOUT_S)
            results[name] = "ok"
        except Exception as exc:
            results[name] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in results.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": results}, status_code=200 if ok else 503
    )
