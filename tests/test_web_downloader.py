"""Tests for Web model and runtime downloader endpoints and SSE progress."""

import asyncio
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict

import pytest

from web.app import create_app
from web.orchestrator import WebOrchestrator
from tests.web_fixtures import (
    AsgiClient,
    MockEngine,
    MockModelDownloader,
)


def test_get_model_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /api/model/status returns pinned model metadata and download state."""
    from core.model_manager import PINNED_MODEL_REPO, PINNED_MODEL_REVISION, TOTAL_MODEL_BYTES

    mock_dl = MockModelDownloader(
        is_downloading=False,
        bytes_downloaded=0,
        total_bytes=TOTAL_MODEL_BYTES,
        current_file="",
        percent=0.0,
    )
    app = create_app(upload_dir=tmp_path, model_downloader=mock_dl)
    client = AsgiClient(app)

    # 1. When local model paths are not present
    monkeypatch.setattr("web.app.get_local_model_paths", lambda *args, **kwargs: None)
    status, _, body = client.get("/api/model/status")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["repo"] == PINNED_MODEL_REPO
    assert data["revision"] == PINNED_MODEL_REVISION
    assert data["downloaded"] is False
    assert data["model_path"] is None
    assert data["mmproj_path"] is None
    assert data["total_bytes"] == TOTAL_MODEL_BYTES
    assert data["is_downloading"] is False
    assert data["bytes_downloaded"] == 0
    assert data["percent"] == 0.0

    # 2. When local model paths are present
    fake_model = tmp_path / "GLM-OCR-Q8_0.gguf"
    fake_mmproj = tmp_path / "mmproj-GLM-OCR-Q8_0.gguf"
    monkeypatch.setattr(
        "web.app.get_local_model_paths",
        lambda *args, **kwargs: (fake_model, fake_mmproj),
    )
    status, _, body = client.get("/api/model/status")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["downloaded"] is True
    assert data["model_path"] == str(fake_model)
    assert data["mmproj_path"] == str(fake_mmproj)


def test_post_model_download_rejects_client_inputs(tmp_path: Path) -> None:
    """Verify POST /api/model/download rejects forbidden client-controlled parameters with HTTP 400."""
    mock_dl = MockModelDownloader()
    app = create_app(upload_dir=tmp_path, model_downloader=mock_dl)
    client = AsgiClient(app)

    forbidden_payloads = [
        {"url": "http://evil.com/model.gguf"},
        {"repo": "malicious/repo"},
        {"revision": "attacker-branch"},
        {"filename": "backdoor.gguf"},
        {"path": "/etc/shadow"},
        {"dest": "C:\\Windows\\System32"},
        {"url": ""},
        {"repo": "   "},
        {"nested": {"url": "http://evil.com"}},
    ]

    for payload in forbidden_payloads:
        status, _, body = client.post(
            "/api/model/download",
            headers={"content-type": "application/json"},
            body=json.dumps(payload).encode("utf-8"),
        )
        assert status == 400, f"Expected 400 for payload {payload}, got {status}"
        resp_data = json.loads(body.decode("utf-8"))
        assert "Client-controlled download targets are strictly prohibited" in resp_data["detail"]

    # Falsy JSON payloads must be rejected with HTTP 400
    for falsy_body in [b"[]", b'""', b"false", b"null", b"0"]:
        status, _, body = client.post(
            "/api/model/download",
            headers={"content-type": "application/json"},
            body=falsy_body,
        )
        assert status == 400, f"Expected 400 for falsy body {falsy_body!r}, got {status}"
        resp_data = json.loads(body.decode("utf-8"))
        assert "Client-controlled download targets are strictly prohibited" in resp_data["detail"]

    # Also test query parameter injection (any query parameter is rejected)
    for q in ["url=http://evil.com", "foo=bar", "repo=custom"]:
        status, _, body = client.request(
            "POST",
            "/api/model/download",
            query_string=q,
        )
        assert status == 400
        resp_data = json.loads(body.decode("utf-8"))
        assert "Client-controlled download targets are strictly prohibited" in resp_data["detail"]


def test_post_model_download_starts_and_reports_202(tmp_path: Path) -> None:
    """Verify POST /api/model/download initiates background download and returns 202 Accepted."""
    mock_dl = MockModelDownloader(is_downloading=False)
    app = create_app(upload_dir=tmp_path, model_downloader=mock_dl)
    client = AsgiClient(app)

    status, _, body = client.post(
        "/api/model/download",
        headers={"content-type": "application/json"},
        body=b"{}",
    )
    assert status == 202
    resp_data = json.loads(body.decode("utf-8"))
    assert resp_data["started"] is True
    assert "Model download initiated" in resp_data["message"]

    assert mock_dl.download_started.wait(timeout=2.0) is True
    # Verify completion payload is broadcast and recorded in app.state
    for _ in range(40):
        if app.state.last_model_download_status and app.state.last_model_download_status.get("status") == "completed":
            break
        time.sleep(0.05)
    assert app.state.last_model_download_status is not None
    assert app.state.last_model_download_status.get("status") == "completed"
    assert app.state.last_model_download_status.get("downloaded") is True


def test_post_model_download_conflict_409(tmp_path: Path) -> None:
    """Verify POST /api/model/download returns 409 Conflict if download is already in progress."""
    mock_dl = MockModelDownloader(is_downloading=True)
    app = create_app(upload_dir=tmp_path, model_downloader=mock_dl)
    client = AsgiClient(app)

    status, _, body = client.post(
        "/api/model/download",
        headers={"content-type": "application/json"},
        body=b"{}",
    )
    assert status == 409
    resp_data = json.loads(body.decode("utf-8"))
    assert "Model download is already in progress" in resp_data["detail"]


def test_post_model_download_cancel(tmp_path: Path) -> None:
    """Verify POST /api/model/download/cancel cancels active download or reports not active."""
    # 1. When not downloading
    mock_dl_idle = MockModelDownloader(is_downloading=False)
    app_idle = create_app(upload_dir=tmp_path, model_downloader=mock_dl_idle)
    client_idle = AsgiClient(app_idle)

    status, _, body = client_idle.post("/api/model/download/cancel")
    assert status == 200
    resp_idle = json.loads(body.decode("utf-8"))
    assert resp_idle["cancelled"] is False
    assert "No active download to cancel" in resp_idle["message"]

    # 2. When downloading
    mock_dl_active = MockModelDownloader(is_downloading=True)
    app_active = create_app(upload_dir=tmp_path, model_downloader=mock_dl_active)
    client_active = AsgiClient(app_active)

    status, _, body = client_active.post("/api/model/download/cancel")
    assert status == 200
    resp_active = json.loads(body.decode("utf-8"))
    assert resp_active["cancelled"] is True
    assert "Download cancellation requested" in resp_active["message"]
    assert mock_dl_active.cancel_called.is_set() is True


def test_model_download_sse_progress_broadcasting(tmp_path: Path) -> None:
    """Verify model download progress events are broadcast over /api/events SSE stream."""
    mock_engine = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_engine)  # type: ignore[arg-type]
    mock_dl = MockModelDownloader(is_downloading=False)
    app = create_app(
        engine=mock_engine,  # type: ignore[arg-type]
        orchestrator=orchestrator,
        upload_dir=tmp_path,
        model_downloader=mock_dl,
    )

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8000")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }

    resp_headers: Dict[str, str] = {}
    resp_status = 0
    resp_body_chunks = []
    progress_received = asyncio.Event()

    async def receive() -> Dict[str, Any]:
        await progress_received.wait()
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
            if b"model_download_progress" in body and b"GLM-OCR-Q8_0.gguf" in body:
                progress_received.set()

    async def _run() -> None:
        app_task = asyncio.create_task(app(scope, receive, send))

        # Wait until SSE listener is registered
        for _ in range(50):
            with orchestrator._lock:
                if len(orchestrator._subscribers) > 0:
                    break
            await asyncio.sleep(0.02)

        # Trigger download which notifies progress callback
        client = AsgiClient(app)
        await asyncio.to_thread(
            client.post,
            "/api/model/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )

        try:
            await asyncio.wait_for(progress_received.wait(), timeout=3.0)
        finally:
            orchestrator.stop()
            app_task.cancel()
            try:
                await app_task
            except (asyncio.CancelledError, Exception):
                pass

    try:
        asyncio.run(_run())
    finally:
        orchestrator.stop()

    assert resp_status == 200
    assert "text/event-stream" in resp_headers.get("content-type", "")
    full_body = b"".join(resp_body_chunks).decode("utf-8")
    assert "model_download_progress" in full_body
    assert "GLM-OCR-Q8_0.gguf" in full_body
    assert "48.79" in full_body


def test_get_runtime_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /api/runtime/status returns runtime installation metadata and download state."""
    from core.hardware import PINNED_LLAMA_BUILD, HardwareProfile

    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # Mock hardware profile to return "cpu" recommended backend
    fake_profile = HardwareProfile(
        cpu_name="Test CPU",
        recommended_backend="cpu",
    )
    monkeypatch.setattr("web.app.get_cached_hardware_profile", lambda *args, **kwargs: fake_profile)

    # 1. When runtime is not installed
    monkeypatch.setattr("web.app.get_installed_runtime_path", lambda *args, **kwargs: None)
    status, _, body = client.get("/api/runtime/status")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["installed"] is False
    assert data["is_downloading"] is False
    assert data["tag"] == PINNED_LLAMA_BUILD
    assert data["backend"] == "cpu"
    assert data["executable_path"] is None
    assert "llama-server" in data["expected_path"]
    assert "not installed" in data["message"].lower()

    # 2. When runtime is installed
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.touch()
    monkeypatch.setattr("web.app.get_installed_runtime_path", lambda *args, **kwargs: fake_exe)
    status, _, body = client.get("/api/runtime/status")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["installed"] is True
    assert data["is_downloading"] is False
    assert data["tag"] == PINNED_LLAMA_BUILD
    assert data["backend"] == "cpu"
    assert data["executable_path"] == str(fake_exe)
    assert data["percent"] == 100.0


def test_post_runtime_download_starts_and_reports_202(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /api/runtime/download initiates background download and invokes ensure_runtime."""
    from core.hardware import HardwareProfile

    download_started = threading.Event()
    download_finished = threading.Event()
    fake_exe = tmp_path / "llama-server.exe"

    def mock_ensure_runtime(backend: str, tag: str, progress_callback: Any = None, **kwargs: Any) -> Path:
        download_started.set()
        if progress_callback:
            progress_callback("Downloading test-archive...", 500, 1000)
        download_finished.wait(timeout=2.0)
        return fake_exe

    monkeypatch.setattr("web.app.ensure_runtime", mock_ensure_runtime)
    monkeypatch.setattr(
        "web.app.get_cached_hardware_profile",
        lambda *args, **kwargs: HardwareProfile(cpu_name="Test CPU", recommended_backend="cpu"),
    )

    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        status, _, body = client.post(
            "/api/runtime/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )
        assert status == 202
        resp_data = json.loads(body.decode("utf-8"))
        assert resp_data["started"] is True
        assert "Runtime download initiated" in resp_data["message"]

        assert download_started.wait(timeout=2.0) is True

        # While downloading, GET /api/runtime/status should report is_downloading=True
        status, _, body = client.get("/api/runtime/status")
        assert status == 200
        status_data = json.loads(body.decode("utf-8"))
        assert status_data["is_downloading"] is True
        assert status_data["percent"] == 50.0
        assert "Downloading test-archive..." in status_data["message"]
    finally:
        download_finished.set()

    # Wait for background thread to complete
    for _ in range(50):
        if not getattr(app.state, "is_runtime_downloading", False):
            break
        time.sleep(0.02)

    assert getattr(app.state, "is_runtime_downloading", False) is False


def test_post_runtime_download_multipart_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify POST /api/runtime/download tracks part and total_parts in progress and status endpoint."""
    from core.hardware import HardwareProfile

    download_started = threading.Event()
    download_finished = threading.Event()
    fake_exe = tmp_path / "llama-server.exe"

    def mock_ensure_runtime(backend: str, tag: str, progress_callback: Any = None, **kwargs: Any) -> Path:
        download_started.set()
        if progress_callback:
            progress_callback("Downloading [1/2] cudart.zip...", 250, 1000, part=1, total_parts=2)
        download_finished.wait(timeout=2.0)
        return fake_exe

    monkeypatch.setattr("web.app.ensure_runtime", mock_ensure_runtime)
    monkeypatch.setattr(
        "web.app.get_cached_hardware_profile",
        lambda *args, **kwargs: HardwareProfile(cpu_name="Test CPU", recommended_backend="cuda"),
    )

    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        status, _, body = client.post(
            "/api/runtime/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )
        assert status == 202
        assert download_started.wait(timeout=2.0) is True

        status, _, body = client.get("/api/runtime/status")
        assert status == 200
        status_data = json.loads(body.decode("utf-8"))
        assert status_data["is_downloading"] is True
        assert status_data["part"] == 1
        assert status_data["total_parts"] == 2
        assert "Downloading [1/2] cudart.zip..." in status_data["message"]
    finally:
        download_finished.set()

    for _ in range(50):
        if not getattr(app.state, "is_runtime_downloading", False):
            break
        time.sleep(0.02)


def test_post_runtime_download_regex_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify on_progress extracts part and total_parts via regex fallback when kwargs are not passed."""
    from core.hardware import HardwareProfile

    download_started = threading.Event()
    download_finished = threading.Event()
    fake_exe = tmp_path / "llama-server.exe"

    def mock_ensure_runtime(backend: str, tag: str, progress_callback: Any = None, **kwargs: Any) -> Path:
        download_started.set()
        if progress_callback:
            progress_callback("Extracting [2/3] llama-bin.zip...", 0, 0)
        download_finished.wait(timeout=2.0)
        return fake_exe

    monkeypatch.setattr("web.app.ensure_runtime", mock_ensure_runtime)
    monkeypatch.setattr(
        "web.app.get_cached_hardware_profile",
        lambda *args, **kwargs: HardwareProfile(cpu_name="Test CPU", recommended_backend="cuda"),
    )

    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        status, _, body = client.post(
            "/api/runtime/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )
        assert status == 202
        assert download_started.wait(timeout=2.0) is True

        status, _, body = client.get("/api/runtime/status")
        assert status == 200
        status_data = json.loads(body.decode("utf-8"))
        assert status_data["part"] == 2
        assert status_data["total_parts"] == 3
    finally:
        download_finished.set()

    for _ in range(50):
        if not getattr(app.state, "is_runtime_downloading", False):
            break
        time.sleep(0.02)


def test_post_runtime_download_conflict_409(tmp_path: Path) -> None:
    """Verify POST /api/runtime/download returns 409 Conflict if download is already in progress."""
    app = create_app(upload_dir=tmp_path)
    app.state.is_runtime_downloading = True
    client = AsgiClient(app)

    status, _, body = client.post(
        "/api/runtime/download",
        headers={"content-type": "application/json"},
        body=b"{}",
    )
    assert status == 409
    resp_data = json.loads(body.decode("utf-8"))
    assert "Runtime download is already in progress" in resp_data["detail"]


def test_post_runtime_download_cancel(tmp_path: Path) -> None:
    """Verify POST /api/runtime/download/cancel returns non-cancellable notice."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    status, _, body = client.post("/api/runtime/download/cancel")
    assert status == 200
    resp_data = json.loads(body.decode("utf-8"))
    assert resp_data["cancelled"] is False
    assert "does not support mid-flight cancellation" in resp_data["message"]


def test_post_runtime_download_forbidden_params(tmp_path: Path) -> None:
    """Verify POST /api/runtime/download rejects client-controlled targets with 400 Bad Request."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Body forbidden param (dict, nested dict)
    for payload in [
        b'{"url": "http://malicious.example.com/binary.zip"}',
        b'{"nested": {"dest": "/root"}}',
    ]:
        status, _, body = client.post(
            "/api/runtime/download",
            headers={"content-type": "application/json"},
            body=payload,
        )
        assert status == 400
        resp_data = json.loads(body.decode("utf-8"))
        assert "Client-controlled download targets are strictly prohibited" in resp_data["detail"]

    # Falsy JSON payloads must be rejected with HTTP 400
    for falsy_body in [b"[]", b'""', b"false", b"null", b"0"]:
        status, _, body = client.post(
            "/api/runtime/download",
            headers={"content-type": "application/json"},
            body=falsy_body,
        )
        assert status == 400
        resp_data = json.loads(body.decode("utf-8"))
        assert "Client-controlled download targets are strictly prohibited" in resp_data["detail"]

    # 2. Query param rejection (any query parameter is rejected)
    for q in ["path=/etc/shadow", "custom=param", "revision=123"]:
        status, _, body = client.request(
            "POST",
            "/api/runtime/download",
            query_string=q,
        )
        assert status == 400
        resp_data = json.loads(body.decode("utf-8"))
        assert "Client-controlled download targets are strictly prohibited" in resp_data["detail"]


def test_runtime_download_sse_progress_broadcasting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify runtime download progress events are broadcast over /api/events SSE stream."""
    from core.hardware import HardwareProfile

    mock_engine = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_engine)  # type: ignore[arg-type]
    fake_exe = tmp_path / "llama-server.exe"

    def mock_ensure_runtime(backend: str, tag: str, progress_callback: Any = None, **kwargs: Any) -> Path:
        if progress_callback:
            progress_callback("Extracting llama-server...", 750, 1000)
        return fake_exe

    monkeypatch.setattr("web.app.ensure_runtime", mock_ensure_runtime)
    monkeypatch.setattr(
        "web.app.get_cached_hardware_profile",
        lambda *args, **kwargs: HardwareProfile(cpu_name="Test CPU", recommended_backend="cpu"),
    )

    app = create_app(
        engine=mock_engine,  # type: ignore[arg-type]
        orchestrator=orchestrator,
        upload_dir=tmp_path,
    )

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8000")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
    }

    resp_headers: Dict[str, str] = {}
    resp_status = 0
    resp_body_chunks = []
    progress_received = asyncio.Event()

    async def receive() -> Dict[str, Any]:
        await progress_received.wait()
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
            if b"runtime_download_progress" in body and b"Extracting llama-server" in body:
                progress_received.set()

    async def _run() -> None:
        app_task = asyncio.create_task(app(scope, receive, send))

        # Wait until SSE listener is registered
        for _ in range(50):
            with orchestrator._lock:
                if len(orchestrator._subscribers) > 0:
                    break
            await asyncio.sleep(0.02)

        # Trigger download which notifies progress callback
        client = AsgiClient(app)
        await asyncio.to_thread(
            client.post,
            "/api/runtime/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )

        try:
            await asyncio.wait_for(progress_received.wait(), timeout=3.0)
        finally:
            orchestrator.stop()
            app_task.cancel()
            try:
                await app_task
            except (asyncio.CancelledError, Exception):
                pass

    try:
        asyncio.run(_run())
    finally:
        orchestrator.stop()

    assert resp_status == 200
    assert "text/event-stream" in resp_headers.get("content-type", "")
    full_body = b"".join(resp_body_chunks).decode("utf-8")
    assert "runtime_download_progress" in full_body
    assert "Extracting llama-server" in full_body
    assert "75.0" in full_body


def test_model_download_cancelled_and_error_branches(tmp_path: Path) -> None:
    """Verify background model download branches for cooperative cancellation and runtime errors."""
    mock_engine = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_engine)

    # 1. Cooperative cancellation branch (downloader returns False)
    class CancelledMockDownloader(MockModelDownloader):
        def download(self) -> bool:
            return False

    dl_cancel = CancelledMockDownloader()
    app_cancel = create_app(
        engine=mock_engine,
        orchestrator=orchestrator,
        upload_dir=tmp_path,
        model_downloader=dl_cancel,
    )
    client_cancel = AsgiClient(app_cancel)

    try:
        status, _, _ = client_cancel.post(
            "/api/model/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )
        assert status == 202

        # Poll until worker thread completes and broadcasts cancelled payload
        deadline = time.time() + 5.0
        while time.time() < deadline:
            st = getattr(app_cancel.state, "last_model_download_status", None)
            if st and st.get("status") == "cancelled":
                break
            time.sleep(0.02)

        st = getattr(app_cancel.state, "last_model_download_status", None)
        assert st is not None
        assert st["status"] == "cancelled"
        assert st["is_downloading"] is False
        assert st["downloaded"] is False
        assert st["error"] == "Download cancelled"
    finally:
        orchestrator.stop()

    # 2. Error branch (downloader raises unexpected exception)
    class FailingMockDownloader(MockModelDownloader):
        def download(self) -> bool:
            raise RuntimeError("Simulated download disk corruption")

    dl_fail = FailingMockDownloader()
    orchestrator_fail = WebOrchestrator(engine=mock_engine)
    app_fail = create_app(
        engine=mock_engine,
        orchestrator=orchestrator_fail,
        upload_dir=tmp_path,
        model_downloader=dl_fail,
    )
    client_fail = AsgiClient(app_fail)

    try:
        status, _, _ = client_fail.post(
            "/api/model/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )
        assert status == 202

        deadline = time.time() + 5.0
        while time.time() < deadline:
            st = getattr(app_fail.state, "last_model_download_status", None)
            if st and st.get("status") == "error":
                break
            time.sleep(0.02)

        st = getattr(app_fail.state, "last_model_download_status", None)
        assert st is not None
        assert st["status"] == "error"
        assert st["is_downloading"] is False
        assert "Simulated download disk corruption" in st["error"]
    finally:
        orchestrator_fail.stop()


def test_runtime_download_error_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify background runtime download error branch updates state and resets downloading flag."""
    mock_engine = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_engine)
    app = create_app(engine=mock_engine, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    def mock_failing_ensure_runtime(*args: Any, **kwargs: Any) -> Path:
        raise RuntimeError("Simulated archive download failure")

    monkeypatch.setattr("web.app.ensure_runtime", mock_failing_ensure_runtime)

    try:
        status, _, _ = client.post(
            "/api/runtime/download",
            headers={"content-type": "application/json"},
            body=b"{}",
        )
        assert status == 202

        deadline = time.time() + 5.0
        while time.time() < deadline:
            st = getattr(app.state, "last_runtime_download_status", None)
            if st and st.get("error") is not None:
                break
            time.sleep(0.02)

        st = getattr(app.state, "last_runtime_download_status", None)
        assert st is not None
        assert st["installed"] is False
        assert st["is_downloading"] is False
        assert "Simulated archive download failure" in st["error"]
        assert getattr(app.state, "is_runtime_downloading", False) is False
    finally:
        orchestrator.stop()
