from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

pytestmark = pytest.mark.integration

PASSWORD = "Correct-Horse-9"


@pytest.fixture
def client() -> Iterator[TestClient]:
    from pianoforge.api.main import create_app
    from pianoforge.config import get_settings

    app = create_app(get_settings())
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def signup(client: TestClient, email: str = "pianist@example.com") -> dict[str, Any]:
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "display_name": "Pianist"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


def upload(client: TestClient, path: Path, mime: str = "audio/mpeg", name: str = "song.mp3") -> str:
    r = client.post(
        "/api/v1/uploads",
        json={"filename": name, "size_bytes": path.stat().st_size, "mime_type": mime},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    with path.open("rb") as f:
        s3 = httpx.post(
            body["url"], data=body["fields"], files={"file": (name, f, mime)}, timeout=30
        )
    assert s3.status_code in (200, 201, 204), s3.text
    return str(body["upload_id"])


def create_project(client: TestClient, upload_id: str, **params: Any) -> dict[str, Any]:
    r = client.post("/api/v1/projects", json={"upload_id": upload_id, "params": params})
    assert r.status_code == 202, r.text
    return dict(r.json())


def test_full_pipeline_flow(client: TestClient, mp3_file: Path) -> None:
    signup(client)
    assert client.get("/api/v1/auth/me").json()["email"] == "pianist@example.com"

    upload_id = upload(client, mp3_file)
    created = create_project(client, upload_id, difficulty="beginner")
    project_id = created["project"]["id"]
    job_id = created["job"]["id"]
    assert created["project"]["title"] == "song"

    # Eager Celery ran the whole canvas inside the request.
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "succeeded", job
    assert job["progress"] == 100
    assert job["params"]["difficulty"] == "beginner"

    events = client.get(f"/api/v1/jobs/{job_id}/events").json()
    stages = [e["stage"] for e in events]
    for stage in (
        "ingest",
        "separate",
        "rhythm",
        "tonal",
        "transcribe",
        "merge",
        "arrange",
        "export",
    ):
        assert stage in stages
    assert events == sorted(events, key=lambda e: e["id"])

    detail = client.get(f"/api/v1/projects/{project_id}").json()
    assert detail["asset"]["status"] == "valid"
    # 0.5 s lead-in + 12 bars x 2.4 s + 1 s tail
    assert detail["asset"]["duration_sec"] == pytest.approx(30.3, abs=0.2)
    analysis = detail["analysis"]
    assert analysis["summary"]["key"] == "C major"
    assert analysis["tempo_bpm"] == pytest.approx(100, rel=0.03)
    assert analysis["time_signature"] == "4/4"
    assert analysis["engine_versions"]["separator"] == "hpss@1"

    ir = client.get(f"/api/v1/projects/{project_id}/analysis").json()["ir"]
    assert set(ir["tracks"]) == {"melody", "bass", "harmony"}
    assert len(ir["tracks"]["melody"]["notes"]) > 10
    assert {c["root"] for c in ir["chords"] if c["root"] is not None} >= {0, 5, 7, 9}

    page = client.get("/api/v1/projects").json()
    assert [p["id"] for p in page["items"]] == [project_id]
    assert page["items"][0]["latest_job"]["status"] == "succeeded"

    # WebSocket on a finished job: snapshot then normal close.
    ticket = client.post("/api/v1/ws-ticket", json={"job_id": job_id}).json()["ticket"]
    with client.websocket_connect(f"/ws/jobs/{job_id}?ticket={ticket}") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        assert snap["job"]["status"] == "succeeded"
        assert len(snap["events"]) == len(events)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 1000

    # Tickets are single use.
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(f"/ws/jobs/{job_id}?ticket={ticket}") as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 1008


def test_arrangement_exports_and_rearrange(client: TestClient, mp3_file: Path) -> None:
    signup(client)
    created = create_project(
        client, upload(client, mp3_file), difficulty="beginner", simplify_key=True
    )
    project_id = created["project"]["id"]
    detail = client.get(f"/api/v1/projects/{project_id}").json()
    arr = detail["latest_arrangement"]
    assert arr is not None and arr["status"] == "ready"
    assert arr["difficulty"] == "beginner"
    assert {e["format"] for e in arr["exports"]} == {"midi", "musicxml", "pdf", "wav", "mp3"}
    assert arr["stats"]["measures"] >= 10

    full = client.get(f"/api/v1/arrangements/{arr['id']}").json()
    score = full["score"]
    assert score["difficulty"] == "beginner" and score["key"]["tonic"] == 0
    assert score["tempo_bpm"] == pytest.approx(100, rel=0.03)
    assert max(sum(1 for n in score["notes"] if n["hand"] == "rh" and n["start"] == s)
               for s in {n["start"] for n in score["notes"]}) == 1  # fmt: skip

    # Download: 302 to a presigned URL, and the JSON variant.
    r = client.get(f"/api/v1/arrangements/{arr['id']}/exports/midi", follow_redirects=False)
    assert r.status_code == 302 and "X-Amz-Signature" in r.headers["location"]
    info = client.get(f"/api/v1/arrangements/{arr['id']}/exports/pdf?redirect=false").json()
    assert info["filename"] == "song (Beginner).pdf"
    assert httpx.get(info["url"], timeout=30).content.startswith(b"%PDF")
    midi = httpx.get(r.headers["location"], timeout=30).content
    assert midi.startswith(b"MThd")

    # New parameters -> rearrange job; identical parameters -> existing result.
    r = client.post(
        f"/api/v1/projects/{project_id}/arrangements", json={"params": {"difficulty": "advanced"}}
    )
    assert r.status_code == 202, r.text
    job = client.get(f"/api/v1/jobs/{r.json()['job']['id']}").json()
    assert job["kind"] == "rearrange" and job["status"] == "succeeded", job
    events = client.get(f"/api/v1/jobs/{job['id']}/events").json()
    assert {e["stage"] for e in events} == {"arrange", "export"}
    arrs = client.get(f"/api/v1/projects/{project_id}/arrangements").json()
    assert [a["difficulty"] for a in arrs] == ["advanced", "beginner"]
    assert [a["revision"] for a in arrs] == [2, 1]

    r = client.post(
        f"/api/v1/projects/{project_id}/arrangements", json={"params": {"difficulty": "advanced"}}
    )
    assert r.status_code == 200
    assert r.json()["job"] is None and r.json()["arrangement"]["id"] == arrs[0]["id"]

    bad = client.post(
        f"/api/v1/projects/{project_id}/arrangements",
        json={"params": {"range_low": 60, "range_high": 70}},
    )
    assert bad.status_code == 422


def test_duplicate_upload_reuses_analysis(client: TestClient, mp3_file: Path) -> None:
    signup(client)
    first = create_project(client, upload(client, mp3_file))
    second = create_project(client, upload(client, mp3_file))
    assert client.get(f"/api/v1/jobs/{second['job']['id']}").json()["status"] == "succeeded"

    a = client.get(f"/api/v1/projects/{first['project']['id']}").json()
    b = client.get(f"/api/v1/projects/{second['project']['id']}").json()
    assert a["analysis"]["id"] == b["analysis"]["id"]
    assert a["asset"]["id"] == b["asset"]["id"]
    messages = [
        e["message"] for e in client.get(f"/api/v1/jobs/{second['job']['id']}/events").json()
    ]
    assert any("재사용" in m for m in messages)


def test_invalid_audio_is_rejected_and_deleted(client: TestClient, tmp_path: Path) -> None:
    from pianoforge.storage import get_storage

    signup(client)
    fake = tmp_path / "fake.mp3"
    fake.write_bytes(b"this is not audio" * 100)
    upload_id = upload(client, fake)
    created = create_project(client, upload_id)
    job = client.get(f"/api/v1/jobs/{created['job']['id']}").json()
    assert job["status"] == "failed"
    assert job["error_code"] == "unreadable"
    assert "읽을 수 없습니다" in job["error_message"]

    detail = client.get(f"/api/v1/projects/{created['project']['id']}").json()
    assert detail["asset"]["status"] == "rejected"
    assert detail["analysis"] is None
    me = client.get("/api/v1/auth/me").json()
    assert not get_storage().exists(f"raw/{me['id']}/{upload_id}")


def test_upload_cannot_be_used_twice(
    client: TestClient, mp3_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pianoforge.api.routers import projects

    monkeypatch.setattr(projects, "enqueue_full_pipeline", lambda ctx: str(uuid.uuid4()))
    signup(client)
    upload_id = upload(client, mp3_file)
    create_project(client, upload_id)
    r = client.post("/api/v1/projects", json={"upload_id": upload_id})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "upload_consumed"


def test_delete_account_removes_everything(client: TestClient, mp3_file: Path) -> None:
    from sqlalchemy import text

    from pianoforge.db.session import get_sync_engine

    signup(client)
    create_project(client, upload(client, mp3_file))
    r = client.request("DELETE", "/api/v1/auth/me", json={"password": "wrong-Pass-1"})
    assert r.status_code == 401
    r = client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD})
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    with get_sync_engine().connect() as conn:
        for table in ("users", "projects", "audio_assets", "jobs", "analyses"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table


def test_upload_validation(client: TestClient) -> None:
    signup(client)
    r = client.post(
        "/api/v1/uploads", json={"filename": "a.exe", "size_bytes": 10, "mime_type": "audio/mpeg"}
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/uploads", json={"filename": "a.mp3", "size_bytes": 10, "mime_type": "video/mp4"}
    )
    assert r.status_code == 415
    r = client.post(
        "/api/v1/uploads",
        json={"filename": "a.mp3", "size_bytes": 10**9, "mime_type": "audio/mpeg"},
    )
    assert r.status_code == 413
    # Project creation before the object exists in storage.
    r = client.post(
        "/api/v1/uploads", json={"filename": "a.mp3", "size_bytes": 10, "mime_type": "audio/mpeg"}
    )
    r = client.post("/api/v1/projects", json={"upload_id": r.json()["upload_id"]})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "upload_incomplete"


def test_csrf_required_for_cookie_sessions(client: TestClient) -> None:
    signup(client)
    token = client.headers.pop("X-CSRF-Token")
    r = client.post(
        "/api/v1/uploads", json={"filename": "a.mp3", "size_bytes": 10, "mime_type": "audio/mpeg"}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"
    client.headers["X-CSRF-Token"] = token
    r = client.post(
        "/api/v1/uploads", json={"filename": "a.mp3", "size_bytes": 10, "mime_type": "audio/mpeg"}
    )
    assert r.status_code == 201


def test_bearer_token_skips_csrf(client: TestClient) -> None:
    body = signup(client)
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token")
    r = client.post(
        "/api/v1/uploads",
        json={"filename": "a.mp3", "size_bytes": 10, "mime_type": "audio/mpeg"},
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert r.status_code == 201


def test_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    signup(client)
    old_refresh = client.cookies.get("pf_refresh")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200, r.text
    new_refresh = client.cookies.get("pf_refresh")
    assert new_refresh and new_refresh != old_refresh

    # Replaying the rotated token revokes the whole family.
    client.cookies.set("pf_refresh", old_refresh, path="/api/v1/auth")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "token_reuse"
    client.cookies.set("pf_refresh", new_refresh, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_login_and_logout(client: TestClient) -> None:
    signup(client)
    client.cookies.clear()
    bad = client.post(
        "/api/v1/auth/login", json={"email": "pianist@example.com", "password": "wrong-Pass-1"}
    )
    assert bad.status_code == 401
    ok = client.post(
        "/api/v1/auth/login", json={"email": "PIANIST@example.com", "password": PASSWORD}
    )
    assert ok.status_code == 200
    client.headers["X-CSRF-Token"] = ok.json()["csrf_token"]
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    dup = client.post(
        "/api/v1/auth/signup",
        json={"email": "pianist@example.com", "password": PASSWORD, "display_name": "x"},
    )
    assert dup.status_code == 409


def test_other_users_cannot_see_resources(client: TestClient, mp3_file: Path) -> None:
    signup(client, "alice@example.com")
    created = create_project(client, upload(client, mp3_file))
    client.cookies.clear()
    signup(client, "bob@example.com")
    assert client.get(f"/api/v1/projects/{created['project']['id']}").status_code == 404
    assert client.get(f"/api/v1/jobs/{created['job']['id']}").status_code == 404
    assert (
        client.post("/api/v1/ws-ticket", json={"job_id": created["job"]["id"]}).status_code == 404
    )
    assert client.get("/api/v1/projects").json()["items"] == []


def test_cancel_queued_job_and_ws_origin(
    client: TestClient, mp3_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pianoforge.api.routers import projects

    monkeypatch.setattr(projects, "enqueue_full_pipeline", lambda ctx: str(uuid.uuid4()))
    signup(client)
    created = create_project(client, upload(client, mp3_file))
    job_id = created["job"]["id"]
    assert created["job"]["status"] == "queued"

    ticket = client.post("/api/v1/ws-ticket", json={"job_id": job_id}).json()["ticket"]
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(
            f"/ws/jobs/{job_id}?ticket={ticket}", headers={"origin": "https://evil.example"}
        ) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 1008

    r = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").status_code == 409

    # Concurrency limit counts only active jobs, so a new project is accepted.
    r = client.delete(f"/api/v1/projects/{created['project']['id']}")
    assert r.status_code == 204
    assert client.get(f"/api/v1/projects/{created['project']['id']}").status_code == 404


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json()["status"] == "ok"
    ready = client.get("/readyz")
    assert ready.status_code == 200, ready.text
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}
    r = client.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Request-ID"]
