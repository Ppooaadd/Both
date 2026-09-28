"""Real-time job progress over WebSocket.

Browsers cannot set headers on WebSocket requests, so the client first obtains
a single-use ticket (30 s) over authenticated REST, then connects with
``?ticket=``. The Origin header is checked against the CORS allow-list.

Protocol (server -> client, JSON text frames):
    {"type": "snapshot", "job": {...}, "events": [...]}   once, on connect
    {"type": "progress" | "event" | "status", ...}        live, from Redis
    {"type": "ping"}                                      every 20 s idle
The server closes with 1000 after a terminal ``status``. Clients reconnect
with ``last_event_id`` to receive only missed events.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis
from sqlalchemy import select

from pianoforge.api.deps import CurrentUser, DbDep, RedisDep, SettingsDep, user_rate_limit
from pianoforge.api.routers.jobs import owned_job
from pianoforge.api.schemas import JobEventOut, JobOut, WsTicketIn, WsTicketOut
from pianoforge.api.security import issue_ws_ticket, redeem_ws_ticket
from pianoforge.config import get_settings
from pianoforge.db.models import Job, JobEvent, Project
from pianoforge.db.session import get_async_sessionmaker
from pianoforge.events import channel
from pianoforge.logging import get_logger

log = get_logger(__name__)
# POST {api_prefix}/ws-ticket
router = APIRouter(tags=["realtime"])
# WS /ws/jobs/{id} at the root so the reverse proxy can route /ws separately.
socket_router = APIRouter(tags=["realtime"])

HEARTBEAT_S = 20.0
TERMINAL = {"succeeded", "failed", "canceled"}


@router.post(
    "/ws-ticket", response_model=WsTicketOut, dependencies=[Depends(user_rate_limit("ws-ticket"))]
)
async def create_ws_ticket(
    body: WsTicketIn, user: CurrentUser, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> WsTicketOut:
    await owned_job(db, user, body.job_id)
    ticket = await issue_ws_ticket(redis, user.id, body.job_id, settings)
    return WsTicketOut(
        ticket=ticket, expires_in=settings.ws_ticket_ttl_s, url=f"/ws/jobs/{body.job_id}"
    )


async def _snapshot(
    user_id: uuid.UUID, job_id: uuid.UUID, last_event_id: int
) -> dict[str, object] | None:
    async with get_async_sessionmaker()() as db:
        job = (
            await db.execute(
                select(Job)
                .join(Project, Project.id == Job.project_id)
                .where(Job.id == job_id, Project.user_id == user_id)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        events = (
            await db.execute(
                select(JobEvent)
                .where(JobEvent.job_id == job_id, JobEvent.id > last_event_id)
                .order_by(JobEvent.id)
                .limit(500)
            )
        ).scalars()
        return {
            "type": "snapshot",
            "job": JobOut.model_validate(job).model_dump(mode="json"),
            "events": [JobEventOut.model_validate(e).model_dump(mode="json") for e in events],
        }


def _origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    # Non-browser clients send no Origin; the ticket still authenticates them.
    return origin is None or origin in get_settings().cors_origins


@socket_router.websocket("/ws/jobs/{job_id}")
async def job_stream(
    ws: WebSocket,
    job_id: uuid.UUID,
    ticket: str = Query(min_length=10, max_length=100),
    last_event_id: int = Query(default=0, ge=0),
) -> None:
    redis: Redis = ws.app.state.redis
    if not _origin_allowed(ws):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    redeemed = await redeem_ws_ticket(redis, ticket)
    if redeemed is None or redeemed[1] != job_id:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id = redeemed[0]

    await ws.accept()
    pubsub = redis.pubsub()
    # Subscribe before reading the snapshot so no update falls in between.
    await pubsub.subscribe(channel(job_id))
    try:
        snap = await _snapshot(user_id, job_id, last_event_id)
        if snap is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.send_json(snap)
        job_state = snap["job"]
        if isinstance(job_state, dict) and job_state.get("status") in TERMINAL:
            await ws.close(code=status.WS_1000_NORMAL_CLOSURE)
            return

        async def pump() -> None:
            loop = asyncio.get_running_loop()
            last_sent = loop.time()
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=HEARTBEAT_S)
                if msg is None:
                    # None also comes back right after a swallowed subscribe ack.
                    if loop.time() - last_sent >= HEARTBEAT_S:
                        await ws.send_json({"type": "ping"})
                        last_sent = loop.time()
                    continue
                last_sent = loop.time()
                data = msg["data"]
                text = data if isinstance(data, str) else data.decode()
                await ws.send_text(text)
                payload = json.loads(text)
                if payload.get("type") == "status" and payload.get("status") in TERMINAL:
                    return

        async def drain_client() -> None:
            # Client frames are ignored; receiving detects disconnects promptly.
            while True:
                await ws.receive_text()

        pump_task = asyncio.create_task(pump())
        client_task = asyncio.create_task(drain_client())
        done, pending = await asyncio.wait(
            {pump_task, client_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await t
        errors = [t.exception() for t in done]
        if pump_task in done and errors == [None]:
            await ws.close(code=status.WS_1000_NORMAL_CLOSURE)
    except WebSocketDisconnect:
        pass
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel(job_id))
            await pubsub.aclose()  # type: ignore[no-untyped-call]
