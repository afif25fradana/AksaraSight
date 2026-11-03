"""Tests for Web server management endpoints, process logs, and state guards."""

import asyncio
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch
import urllib3

from PIL import Image
import pytest

from config.settings import Settings
from core.client import ServerOfflineError
from core.engine import OCREngine
from core.models import JobConfig, JobStatus as CoreJobStatus, OCRResult, PageResult
from core.server_manager import ServerOwnership, ServerStatus
from web.app import create_app
from web.orchestrator import JobState, JobStatus, WebOrchestrator
from tests.web_fixtures import (
    AsgiClient,
    MockEngine,
    MockServerManager,
    _create_sample_png_bytes,
)


def test_server_offline_handling(tmp_path: Path) -> None:
    """Verify ServerOfflineError is caught cleanly in health probe and extraction."""
    mock_eng = MockEngine(failure_mode="offline")
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Health probe detects offline
    status, _, resp = client.get("/health")
    assert status == 200
    health = json.loads(resp.decode("utf-8"))
    assert health["status"] == "offline"
    assert "Simulated offline backend" in health["error"]

    # 2. Extract job fails cleanly
    png_bytes = _create_sample_png_bytes()
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("offline_test.png", png_bytes, "image/png")}
    )
    _, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    job_id = json.loads(resp.decode("utf-8"))["id"]

    client.post(f"/api/documents/{job_id}/extract")

    for _ in range(50):
        job = orchestrator.get_job(job_id)
        if job and job.status == JobStatus.FAILED:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.FAILED
    assert "Simulated backend disconnect" in (job.error or "")

    orchestrator.stop()


def test_patch_settings_server_stop_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify PATCH /api/settings conditionally stops managed server on server config changes."""
    pre_env = dict(os.environ)
    try:
        monkeypatch.chdir(tmp_path)
        mock_mgr = MockServerManager(
            status=ServerStatus.READY,
            ownership=ServerOwnership.MANAGED,
            message="Active managed backend",
        )
        app = create_app(
            settings=Settings(),
            server_manager=mock_mgr,
            upload_dir=tmp_path,
            env_path=tmp_path / ".env",
        )
        app.state.server_managed = True
        client = AsgiClient(app)

        # 1. Non-server key change (e.g. dpi) -> server_stopped is False, mock_mgr.stop_calls == 0
        patch_body = json.dumps({"dpi": 200}).encode("utf-8")
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=patch_body,
        )
        assert status == 200
        data = json.loads(resp.decode("utf-8"))
        assert data["updated"] is True
        assert data["server_stopped"] is False
        assert mock_mgr.stop_calls == 0
        assert app.state.server_managed is True

        # 2. Server-affecting key change (e.g. backend) -> server_stopped is True, mock_mgr.stop_calls == 1
        patch_body = json.dumps({"backend": "ollama"}).encode("utf-8")
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=patch_body,
        )
        assert status == 200
        data = json.loads(resp.decode("utf-8"))
        assert data["updated"] is True
        assert data["server_stopped"] is True
        assert mock_mgr.stop_calls == 1
        assert app.state.server_managed is False

        # 3. Server-affecting key change while already offline -> server_stopped is False
        assert mock_mgr.status == ServerStatus.OFFLINE
        patch_body = json.dumps({"runtime_mode": "custom"}).encode("utf-8")
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=patch_body,
        )
        assert status == 200
        data = json.loads(resp.decode("utf-8"))
        assert data["updated"] is True
        assert data["server_stopped"] is False
        assert mock_mgr.stop_calls == 1
    finally:
        os.environ.clear()
        os.environ.update(pre_env)


def test_server_status_endpoint(tmp_path: Path) -> None:
    """Verify GET /api/server/status returns current server execution and ownership state."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
        message="Active managed backend",
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    client = AsgiClient(app)

    status_code, _, body = client.get("/api/server/status")
    assert status_code == 200
    data = json.loads(body.decode("utf-8"))
    assert data["status"] == "READY"
    assert data["ownership"] == "MANAGED"
    assert data["managed_by_web"] is False
    assert data["message"] == "Active managed backend"
    assert data["endpoint"] == mock_mgr.settings.local_endpoint
    assert data["pid"] is None
    assert len(data["recent_logs"]) == 2


def test_server_start_endpoint(tmp_path: Path) -> None:
    """Verify POST /api/server/start initiates managed server and tracks ownership."""
    mock_mgr = MockServerManager(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    client = AsgiClient(app)

    # First start: boots the server
    status_code, _, body = client.post("/api/server/start")
    assert status_code == 200
    data = json.loads(body.decode("utf-8"))
    assert data["started"] is True
    assert data["status"] == "READY"
    assert data["ownership"] == "MANAGED"
    assert mock_mgr.start_calls == 1
    assert app.state.server_managed is True

    # Subsequent start while running: idempotent no-op with started=False
    status_code, _, body = client.post("/api/server/start")
    assert status_code == 200
    data = json.loads(body.decode("utf-8"))
    assert data["started"] is False
    assert "Server is already running" in data["message"]
    assert mock_mgr.start_calls == 1


def test_server_stop_endpoint_rejects_external(tmp_path: Path) -> None:
    """Verify POST /api/server/stop returns 400 when server is externally managed."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.EXTERNAL,
        message="External llama-server",
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    client = AsgiClient(app)

    status_code, _, body = client.post("/api/server/stop")
    assert status_code == 400
    data = json.loads(body.decode("utf-8"))
    assert "Cannot stop external server" in data["detail"]
    assert mock_mgr.stop_calls == 0


def test_server_stop_endpoint_stops_managed(tmp_path: Path) -> None:
    """Verify POST /api/server/stop stops managed server and clears server_managed state."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
        message="Managed server running",
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    app.state.server_managed = True
    client = AsgiClient(app)

    status_code, _, body = client.post("/api/server/stop")
    assert status_code == 200
    data = json.loads(body.decode("utf-8"))
    assert data["stopped"] is True
    assert data["status"] == "OFFLINE"
    assert data["ownership"] == "NONE"
    assert mock_mgr.stop_calls == 1
    assert app.state.server_managed is False

    # Second stop while already offline: idempotent return stopped=False
    status_code, _, body = client.post("/api/server/stop")
    assert status_code == 200
    data = json.loads(body.decode("utf-8"))
    assert data["stopped"] is False
    assert "Server is not running" in data["message"]


def test_server_stop_rejected_during_job_processing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify server stop and start return 409 Conflict if orchestrator is processing."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    app.state.server_managed = True
    client = AsgiClient(app)

    monkeypatch.setattr(app.state.orchestrator, "is_processing", lambda: True)

    # Stop rejected
    status_code, _, body = client.post("/api/server/stop")
    assert status_code == 409
    data = json.loads(body.decode("utf-8"))
    assert "extraction job is currently in progress" in data["detail"]
    assert mock_mgr.stop_calls == 0

    # Start rejected if offline
    mock_mgr._status = ServerStatus.OFFLINE
    mock_mgr._ownership = ServerOwnership.NONE
    status_code, _, body = client.post("/api/server/start")
    assert status_code == 409
    data = json.loads(body.decode("utf-8"))
    assert "extraction job is in progress" in data["detail"]
    assert mock_mgr.start_calls == 0


def test_server_mutating_routes_require_loopback_origin(tmp_path: Path) -> None:
    """Verify POST /api/server/start and POST /api/server/stop reject non-loopback Origin with 403."""
    mock_mgr = MockServerManager()
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    client = AsgiClient(app)

    # Non-loopback Origin rejected with 403
    for path in ("/api/server/start", "/api/server/stop"):
        status_code, _, _ = client.post(
            path,
            headers={"origin": "http://malicious-website.com"},
        )
        assert status_code == 403, f"Expected 403 for {path} with evil origin, got {status_code}"

    # Loopback Origin accepted
    status_code, _, _ = client.post(
        "/api/server/start",
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert status_code == 200


def test_server_stop_external_returns_400(tmp_path: Path) -> None:
    """Verify POST /api/server/stop returns 400 when ownership is external."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.EXTERNAL,
        message="External llama-server",
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    client = AsgiClient(app)

    status_code, _, body = client.post("/api/server/stop")
    assert status_code == 400
    data = json.loads(body.decode("utf-8"))
    assert "Cannot stop external server" in data["detail"]
    assert mock_mgr.stop_calls == 0


def test_server_stop_while_processing_returns_409(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /api/server/stop returns 409 when extraction is active."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    app.state.server_managed = True
    client = AsgiClient(app)

    monkeypatch.setattr(app.state.orchestrator, "is_processing", lambda: True)

    status_code, _, body = client.post("/api/server/stop")
    assert status_code == 409
    data = json.loads(body.decode("utf-8"))
    assert "extraction job is currently in progress" in data["detail"]
    assert mock_mgr.stop_calls == 0


def test_server_start_while_processing_returns_409(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /api/server/start returns 409 when extraction is active."""
    mock_mgr = MockServerManager(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    client = AsgiClient(app)

    monkeypatch.setattr(app.state.orchestrator, "is_processing", lambda: True)

    status_code, _, body = client.post("/api/server/start")
    assert status_code == 409
    data = json.loads(body.decode("utf-8"))
    assert "extraction job is in progress" in data["detail"]
    assert mock_mgr.start_calls == 0


def test_server_logs_stream_origin_security(tmp_path: Path) -> None:
    """Verify GET /api/server/logs/stream rejects foreign Origin with 403, and allows matching or no Origin."""
    mock_mgr = MockServerManager()
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path, allowed_port=8000)
    client = AsgiClient(app)

    # 1. Foreign origin returns 403 Forbidden
    status_code, _, body = client.get(
        "/api/server/logs/stream",
        headers={"origin": "http://evil.com"},
    )
    assert status_code == 403
    assert body == b"Forbidden"

    # 2. Matching origin connects (200 status_code and text/event-stream)
    scope_valid = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/server/logs/stream",
        "raw_path": b"/api/server/logs/stream",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"origin", b"http://127.0.0.1:8000"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }
    resp_status = 0
    connected = asyncio.Event()

    async def receive_valid():
        await connected.wait()
        return {"type": "http.disconnect"}

    async def send_valid(message):
        nonlocal resp_status
        if message["type"] == "http.response.start":
            resp_status = message["status"]
            connected.set()

    async def _run_valid():
        task = asyncio.create_task(app(scope_valid, receive_valid, send_valid))
        try:
            await asyncio.wait_for(connected.wait(), timeout=3.0)
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run_valid())
    assert resp_status == 200

    # 3. No Origin header connects
    scope_no_origin = dict(scope_valid)
    scope_no_origin["headers"] = [(b"host", b"127.0.0.1:8000")]
    resp_status_no_origin = 0
    connected_no_origin = asyncio.Event()

    async def receive_no_origin():
        await connected_no_origin.wait()
        return {"type": "http.disconnect"}

    async def send_no_origin(message):
        nonlocal resp_status_no_origin
        if message["type"] == "http.response.start":
            resp_status_no_origin = message["status"]
            connected_no_origin.set()

    async def _run_no_origin():
        task = asyncio.create_task(app(scope_no_origin, receive_no_origin, send_no_origin))
        try:
            await asyncio.wait_for(connected_no_origin.wait(), timeout=3.0)
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run_no_origin())
    assert resp_status_no_origin == 200


def test_server_logs_stream_receives_lines(tmp_path: Path) -> None:
    """Verify GET /api/server/logs/stream yields both historical and live log lines."""
    mock_mgr = MockServerManager()
    mock_mgr._log_buffer = ["Historical line 1", "Historical line 2"]
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/server/logs/stream",
        "raw_path": b"/api/server/logs/stream",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8000")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }

    resp_headers: Dict[str, str] = {}
    resp_status = 0
    resp_body_chunks = []
    live_received = asyncio.Event()

    async def receive() -> Dict[str, Any]:
        await live_received.wait()
        return {"type": "http.disconnect"}

    async def send(message: Dict[str, Any]) -> None:
        nonlocal resp_status, resp_headers
        if message["type"] == "http.response.start":
            resp_status = message["status"]
            for k, v in message.get("headers", []):
                resp_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            resp_body_chunks.append(body)
            if b"Live line from worker" in body:
                live_received.set()

    async def _run() -> None:
        app_task = asyncio.create_task(app(scope, receive, send))

        # Wait until listener is registered
        for _ in range(50):
            if len(mock_mgr._log_listeners) > 0:
                break
            await asyncio.sleep(0.02)

        # Broadcast live line
        mock_mgr.broadcast_log("Live line from worker")

        try:
            await asyncio.wait_for(live_received.wait(), timeout=3.0)
        finally:
            app_task.cancel()
            try:
                await app_task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())

    assert resp_status == 200
    assert "text/event-stream" in resp_headers.get("content-type", "")
    full_body = b"".join(resp_body_chunks).decode("utf-8")
    assert "Historical line 1" in full_body
    assert '\\"historical\\": true' in full_body.lower() or '"historical": true' in full_body.lower()
    assert "Live line from worker" in full_body
    assert '\\"historical\\": false' in full_body.lower() or '"historical": false' in full_body.lower()
    assert len(mock_mgr._log_listeners) == 0


def test_server_logs_stream_slow_client_queue_full_drops_cleanly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify log listener drops lines cleanly on asyncio.QueueFull when client is slow."""
    mock_mgr = MockServerManager()
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/server/logs/stream",
        "raw_path": b"/api/server/logs/stream",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8000")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }

    connected = asyncio.Event()
    stop_event = asyncio.Event()
    slow_block = asyncio.Event()
    dropped_items: List[str] = []

    orig_put = asyncio.Queue.put_nowait

    def spy_put(self: asyncio.Queue, item: Any) -> None:
        try:
            return orig_put(self, item)
        except asyncio.QueueFull:
            dropped_items.append(item)
            raise

    async def receive() -> Dict[str, Any]:
        await stop_event.wait()
        return {"type": "http.disconnect"}

    async def send(message: Dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            connected.set()
        elif message["type"] == "http.response.body":
            # Simulate backpressuring/slow client that stops consuming stream
            await slow_block.wait()

    async def _run() -> None:
        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(connected.wait(), timeout=3.0)
        for _ in range(50):
            if len(mock_mgr._log_listeners) > 0:
                break
            await asyncio.sleep(0.01)

        assert len(mock_mgr._log_listeners) == 1
        listener = mock_mgr._log_listeners[0]

        secret_line_prefix = "OCR_SECRET_LINE_NO_LEAK"
        for i in range(250):
            listener(f"{secret_line_prefix}_{i}")

        # Yield control to let scheduled threadsafe callbacks execute
        await asyncio.sleep(0.1)

        assert len(dropped_items) == 50
        assert secret_line_prefix not in caplog.text

        stop_event.set()
        slow_block.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    with patch.object(asyncio.Queue, "put_nowait", spy_put):
        asyncio.run(_run())

    assert len(mock_mgr._log_listeners) == 0


def test_server_start_stop_ownership_matrix(tmp_path: Path) -> None:
    """Exhaustively verify server start and stop behavior across ownership and busy states."""
    # (1) POST /api/server/stop when ownership == ServerOwnership.EXTERNAL raises HTTP 400
    mock_mgr_ext = MockServerManager(status=ServerStatus.READY, ownership=ServerOwnership.EXTERNAL)
    app1 = create_app(server_manager=mock_mgr_ext, upload_dir=tmp_path)
    client1 = AsgiClient(app1)
    status_code, _, body = client1.post("/api/server/stop")
    assert status_code == 400
    assert "Cannot stop external server" in json.loads(body.decode("utf-8"))["detail"]
    assert mock_mgr_ext.stop_calls == 0

    # (2) POST /api/server/stop when ownership == ServerOwnership.NONE returns {"stopped": False, ...}
    mock_mgr_none = MockServerManager(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE)
    app2 = create_app(server_manager=mock_mgr_none, upload_dir=tmp_path)
    app2.state.server_managed = False
    client2 = AsgiClient(app2)
    status_code, _, body = client2.post("/api/server/stop")
    assert status_code == 200
    data2 = json.loads(body.decode("utf-8"))
    assert data2["stopped"] is False
    assert data2["status"] == "OFFLINE"
    assert "Server is not running or not managed" in data2["message"]
    assert mock_mgr_none.stop_calls == 0

    # (3) POST /api/server/start when status == ServerStatus.READY and ownership == ServerOwnership.EXTERNAL
    # returns {"started": False, "ownership": "EXTERNAL", ...}
    mock_mgr_ready_ext = MockServerManager(status=ServerStatus.READY, ownership=ServerOwnership.EXTERNAL)
    app3 = create_app(server_manager=mock_mgr_ready_ext, upload_dir=tmp_path)
    client3 = AsgiClient(app3)
    status_code, _, body = client3.post("/api/server/start")
    assert status_code == 200
    data3 = json.loads(body.decode("utf-8"))
    assert data3["started"] is False
    assert data3["ownership"] == "EXTERNAL"
    assert data3["status"] == "READY"
    assert mock_mgr_ready_ext.start_calls == 0

    # (4) POST /api/server/start while app_orchestrator.is_processing() raises HTTP 409
    mock_mgr_proc = MockServerManager(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE)
    app4 = create_app(server_manager=mock_mgr_proc, upload_dir=tmp_path)
    client4 = AsgiClient(app4)
    with patch.object(app4.state.orchestrator, "is_processing", return_value=True):
        status_code, _, body = client4.post("/api/server/start")
        assert status_code == 409
        assert "extraction job is in progress" in json.loads(body.decode("utf-8"))["detail"]
        assert mock_mgr_proc.start_calls == 0

    # (5) POST /api/server/stop while app_orchestrator.is_processing() raises HTTP 409
    mock_mgr_busy = MockServerManager(status=ServerStatus.READY, ownership=ServerOwnership.MANAGED)
    app5 = create_app(server_manager=mock_mgr_busy, upload_dir=tmp_path)
    app5.state.server_managed = True
    client5 = AsgiClient(app5)
    with patch.object(app5.state.orchestrator, "is_processing", return_value=True):
        status_code, _, body = client5.post("/api/server/stop")
        assert status_code == 409
        assert "extraction job is currently in progress" in json.loads(body.decode("utf-8"))["detail"]
        assert mock_mgr_busy.stop_calls == 0


def test_server_lifecycle_starting_state_guards(tmp_path: Path) -> None:
    """Verify server lifecycle guard routes when server is in STARTING state."""
    mock_mgr = MockServerManager(
        status=ServerStatus.STARTING,
        ownership=ServerOwnership.MANAGED,
        message="Starting llama-server...",
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    app.state.server_managed = True
    client = AsgiClient(app)

    try:
        # 1. POST /api/server/start when STARTING: returns 200, started=False, status="STARTING", no call to start()
        status_code, _, body = client.post("/api/server/start")
        assert status_code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["started"] is False
        assert data["status"] == "STARTING"
        assert mock_mgr.start_calls == 0

        # 2. POST /api/server/stop when STARTING: returns 200, stopped=True, status="OFFLINE", calls mock_mgr.stop()
        status_code, _, body = client.post("/api/server/stop")
        assert status_code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["stopped"] is True
        assert data["status"] == "OFFLINE"
        assert mock_mgr.stop_calls == 1
        assert app.state.server_managed is False
    finally:
        app.state.orchestrator.stop()


def test_server_stop_when_job_queued_permits_stop(tmp_path: Path) -> None:
    """Verify that a QUEUED job permits server stop while a PROCESSING job blocks it."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
        message="Managed server running",
    )
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    app.state.server_managed = True
    client = AsgiClient(app)

    try:
        fake_file = tmp_path / "queued_doc.png"
        fake_file.write_bytes(b"dummy image bytes")

        job = JobState(
            job_id="test-queued-job-1",
            filename="queued_doc.png",
            file_path=fake_file,
            status=JobStatus.QUEUED,
        )
        app.state.orchestrator.register_job(job)

        # 1. Job is QUEUED: is_processing() is False, POST /api/server/stop permits stop (200)
        assert app.state.orchestrator.is_processing() is False
        status_code, _, body = client.post("/api/server/stop")
        assert status_code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["stopped"] is True
        assert data["status"] == "OFFLINE"
        assert mock_mgr.stop_calls == 1

        # 2. Transition job to PROCESSING: is_processing() becomes True, POST /api/server/stop is blocked (409)
        mock_mgr._status = ServerStatus.READY
        mock_mgr._ownership = ServerOwnership.MANAGED
        app.state.server_managed = True
        mock_mgr.stop_calls = 0

        with app.state.orchestrator._lock:
            job.status = JobStatus.PROCESSING

        assert app.state.orchestrator.is_processing() is True
        status_code, _, body = client.post("/api/server/stop")
        assert status_code == 409
        data = json.loads(body.decode("utf-8"))
        assert "currently in progress" in data["detail"]
        assert mock_mgr.stop_calls == 0
    finally:
        app.state.orchestrator.stop()


def test_mid_job_server_death_preserves_extracted_pages_and_exports(tmp_path: Path) -> None:
    """Verify mid-job server disconnect preserves partial extracted pages and exports.

    Specifically tests the direct-exception path through orchestrator.py:344-347
    (where process_document itself raises ServerOfflineError and job.result remains None).
    """
    class MidJobFailureEngine(MockEngine):
        def process_document(
            self,
            source: Any,
            config: Optional[JobConfig] = None,
            cancel_token: Optional[threading.Event] = None,
            progress_callback: Optional[Any] = None,
        ) -> OCRResult:
            if progress_callback:
                progress_callback(
                    1,
                    2,
                    PageResult(
                        page_num=1,
                        markdown="# Page 1 Extracted Content\nSample data",
                        latency=0.12,
                        raw_json={"usage": {"total_tokens": 42}},
                    ),
                )
            raise ServerOfflineError("Local server disconnected mid-job")

    mock_engine = MidJobFailureEngine()
    orchestrator = WebOrchestrator(engine=mock_engine)  # type: ignore[arg-type]
    app = create_app(engine=mock_engine, orchestrator=orchestrator, upload_dir=tmp_path)  # type: ignore[arg-type]
    client = AsgiClient(app)

    try:
        fake_file = tmp_path / "mid_job_fail.png"
        fake_file.write_bytes(b"dummy image bytes")

        job_id = "test-mid-job-death"
        job = JobState(
            job_id=job_id,
            filename="mid_job_fail.png",
            file_path=fake_file,
            page_count=2,
            status=JobStatus.UPLOADED,
        )
        orchestrator.register_job(job)
        orchestrator.enqueue(job_id)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job(job_id)
            if j and j.status == JobStatus.FAILED:
                break
            time.sleep(0.02)

        j = orchestrator.get_job(job_id)
        assert j is not None
        assert j.status == JobStatus.FAILED

        status_code, _, body = client.get("/api/documents")
        assert status_code == 200
        docs = json.loads(body.decode("utf-8"))
        assert len(docs) == 1
        doc = docs[0]
        assert doc["status"] == "Failed"
        assert doc["statusNote"] == "Local server disconnected mid-job"
        assert doc["extractedText"] == "# Page 1 Extracted Content\nSample data"
        assert "1" in doc["pagesData"]
        assert doc["pagesData"]["1"]["text"] == "# Page 1 Extracted Content\nSample data"

        status_code, _, body = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status_code == 200
        assert "# Page 1 Extracted Content\nSample data" in body.decode("utf-8")

        status_code, _, body = client.get(f"/api/documents/{job_id}/export?format=json")
        assert status_code == 200
        parsed_json = json.loads(body.decode("utf-8"))
        page_entry = parsed_json.get("1") or parsed_json.get(1)
        assert page_entry is not None
        assert page_entry["text"] == "# Page 1 Extracted Content\nSample data"

        status_code, _, body = client.get(f"/api/documents/{job_id}/export?format=docx")
        assert status_code == 400
        detail = json.loads(body.decode("utf-8"))["detail"]
        assert "Complete extraction result required for DOCX" in detail
    finally:
        orchestrator.stop()


def test_real_engine_mid_job_server_offline_preserves_pages_and_exports(tmp_path: Path) -> None:
    """Verify real OCREngine aborts cleanly on mid-job ServerOfflineError, preserving pages and exports."""
    class FakeVisionClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete(
            self,
            image_b64: str,
            prompt: str,
            max_tokens: Optional[int] = None,
        ) -> Tuple[str, Dict[str, Any], float, bool]:
            self.calls += 1
            if self.calls == 1:
                return (
                    "# Page 1 Real Engine Content\nExtracted successfully.",
                    {"usage": {"total_tokens": 42}},
                    0.12,
                    False,
                )
            raise ServerOfflineError(
                "Cannot connect to local backend at 'http://localhost:8080/v1/chat/completions'. Ensure llama-server or Ollama is running."
            )

        def verify_multimodal_support(self) -> None:
            pass

        def close(self) -> None:
            pass

    engine = OCREngine(settings=Settings())
    engine.client = FakeVisionClient()

    pdf_path = tmp_path / "real_engine_doc.pdf"
    img1 = Image.new("RGB", (100, 100), color="white")
    img2 = Image.new("RGB", (100, 100), color="white")
    img1.save(pdf_path, save_all=True, append_images=[img2])

    orchestrator = WebOrchestrator(engine=engine)
    app = create_app(engine=engine, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        job_id = "test-real-engine-mid-job-offline"
        job = JobState(
            job_id=job_id,
            filename="real_engine_doc.pdf",
            file_path=pdf_path,
            page_count=2,
            status=JobStatus.UPLOADED,
        )
        orchestrator.register_job(job)
        orchestrator.enqueue(job_id)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job(job_id)
            if j and j.status in (JobStatus.FAILED, JobStatus.SUCCESS):
                break
            time.sleep(0.02)

        j = orchestrator.get_job(job_id)
        assert j is not None
        assert j.status == JobStatus.FAILED
        assert j.error is not None and "Inference backend offline on page 2" in j.error
        assert 1 in j.pages_data
        assert j.pages_data[1]["text"] == "# Page 1 Real Engine Content\nExtracted successfully."
        assert j.result is not None
        assert isinstance(j.result, OCRResult)
        assert j.result.status == CoreJobStatus.FAILED

        status_code, _, body = client.get("/api/documents")
        assert status_code == 200
        docs = json.loads(body.decode("utf-8"))
        assert len(docs) == 1
        doc = docs[0]
        assert doc["status"] == "Failed"
        assert "Inference backend offline on page 2" in (doc.get("statusNote") or "")
        assert doc["extractedText"] == "# Page 1 Real Engine Content\nExtracted successfully."
        assert "1" in doc["pagesData"]

        status_code, _, body = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status_code == 200
        assert "# Page 1 Real Engine Content\nExtracted successfully." in body.decode("utf-8")

        status_code, _, body = client.get(f"/api/documents/{job_id}/export?format=json")
        assert status_code == 200
        assert "Page 1 Real Engine Content" in body.decode("utf-8")

        status_code, _, body = client.get(f"/api/documents/{job_id}/export?format=docx")
        assert status_code == 200
        assert len(body) > 0
    finally:
        orchestrator.stop()


def test_queued_job_fails_cleanly_when_server_stopped_before_execution(tmp_path: Path) -> None:
    """Verify queued job fails cleanly when server is stopped before execution starts."""
    mock_mgr = MockServerManager(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
        message="Managed server running",
    )

    class OfflineClient:
        def complete(
            self,
            image_b64: str,
            prompt: str,
            max_tokens: Optional[int] = None,
        ) -> Tuple[str, Dict[str, Any], float, bool]:
            if mock_mgr.status == ServerStatus.OFFLINE:
                raise ServerOfflineError("Local server is offline")
            return ("Extracted text", {"usage": {"total_tokens": 10}}, 0.05, False)

        def verify_multimodal_support(self) -> None:
            if mock_mgr.status == ServerStatus.OFFLINE:
                raise ServerOfflineError("Local server is offline")

        def close(self) -> None:
            pass

    engine = OCREngine(settings=Settings())
    engine.client = OfflineClient()
    orchestrator = WebOrchestrator(engine=engine)
    app = create_app(
        engine=engine,
        orchestrator=orchestrator,
        server_manager=mock_mgr,
        upload_dir=tmp_path,
    )
    app.state.server_managed = True
    client = AsgiClient(app)

    try:
        sample_file = tmp_path / "queued_stop_doc.png"
        sample_file.write_bytes(_create_sample_png_bytes(50, 50))

        job_id = "test-queued-before-stop"
        job = JobState(
            job_id=job_id,
            filename="queued_stop_doc.png",
            file_path=sample_file,
            status=JobStatus.QUEUED,
        )
        orchestrator.register_job(job)

        assert orchestrator.get_job(job_id).status == JobStatus.QUEUED
        assert mock_mgr.status == ServerStatus.READY

        status_code, _, body = client.post("/api/server/stop")
        assert status_code == 200
        data = json.loads(body.decode("utf-8"))
        assert data["stopped"] is True
        assert data["status"] == "OFFLINE"
        assert mock_mgr.status == ServerStatus.OFFLINE

        orchestrator._queue.put_nowait(job_id)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job(job_id)
            if j and j.status == JobStatus.FAILED:
                break
            time.sleep(0.02)

        j = orchestrator.get_job(job_id)
        assert j is not None
        assert j.status == JobStatus.FAILED

        status_code, _, body = client.get("/api/documents")
        assert status_code == 200
        docs = json.loads(body.decode("utf-8"))
        assert len(docs) == 1
        assert docs[0]["status"] == "Failed"
        assert "Local server is offline" in (docs[0].get("statusNote") or "")
    finally:
        orchestrator.stop()
