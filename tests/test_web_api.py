"""Tests for Web API, security middleware, and queue lifecycle."""

import asyncio
import io
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional, Tuple
import urllib3

from PIL import Image
import pytest

from config.settings import Settings
from core.client import ServerOfflineError
from core.models import JobConfig, JobStatus as CoreJobStatus, OCRResult, PageResult
from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo
from web.app import create_app, enforce_loopback_host
from web.orchestrator import JobStatus, WebOrchestrator


class AsgiClient:
    """Synchronous test client executing raw ASGI requests against FastAPI app."""

    def __init__(
        self,
        app: Any,
        server: Optional[Tuple[str, Optional[int]]] = None,
    ) -> None:
        self.app = app
        self.server = server

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        query_string: str = "",
    ) -> Tuple[int, Dict[str, str], bytes]:
        async def _call():
            server_host = "127.0.0.1"
            pinned_port = getattr(getattr(self.app, "state", None), "allowed_port", None)
            if self.server is not None:
                server_tuple = self.server
            elif pinned_port is not None:
                server_tuple = (server_host, pinned_port)
            else:
                server_tuple = (server_host, None)

            effective_port = server_tuple[1] if (server_tuple and len(server_tuple) > 1) else None
            host_header_val = (
                f"{server_host}:{effective_port}" if effective_port is not None else "127.0.0.1:8000"
            )
            req_headers = {"host": host_header_val}
            if headers:
                req_headers.update(headers)

            headers_list = [
                (k.lower().encode("latin-1"), v.encode("latin-1"))
                for k, v in req_headers.items()
            ]

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.1"},
                "http_version": "1.1",
                "method": method.upper(),
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("latin-1"),
                "query_string": query_string.encode("latin-1"),
                "headers": headers_list,
                "client": ("127.0.0.1", 12345),
                "server": server_tuple,
            }
            resp_headers: Dict[str, str] = {}
            resp_status = 200
            resp_body_chunks = []

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            async def send(message):
                nonlocal resp_status, resp_headers
                if message["type"] == "http.response.start":
                    resp_status = message["status"]
                    for k, v in message.get("headers", []):
                        resp_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
                elif message["type"] == "http.response.body":
                    resp_body_chunks.append(message.get("body", b""))

            await self.app(scope, receive, send)
            return resp_status, resp_headers, b"".join(resp_body_chunks)

        return asyncio.run(_call())

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        query_string: str = "",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("GET", path, headers=headers, query_string=query_string)

    def post(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("POST", path, headers=headers, body=body)

    def delete(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        query_string: str = "",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("DELETE", path, headers=headers, query_string=query_string)

    def put(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("PUT", path, headers=headers, body=body)

    def patch(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("PATCH", path, headers=headers, body=body)


def _create_sample_png_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MockEngine:
    """Mock OCR engine for controlled end-to-end web testing."""

    def __init__(
        self,
        failure_mode: Optional[str] = None,
        process_gate: Optional[threading.Event] = None,
        processing_started: Optional[threading.Event] = None,
    ) -> None:
        self.failure_mode = failure_mode
        self.last_cancel_token: Optional[threading.Event] = None
        self.process_delay: float = 0.0
        self.process_gate = process_gate
        self.processing_started = processing_started
        self.settings: Settings = Settings()
        self.last_config: Optional[JobConfig] = None

    def verify_backend(self, force: bool = False) -> None:
        if self.failure_mode == "offline":
            raise ServerOfflineError("Simulated offline backend")

    def process_document(
        self,
        source: Any,
        config: Optional[JobConfig] = None,
        cancel_token: Optional[threading.Event] = None,
        progress_callback: Optional[Any] = None,
    ) -> OCRResult:
        self.last_cancel_token = cancel_token
        self.last_config = config
        if self.processing_started:
            self.processing_started.set()
        if self.process_gate:
            self.process_gate.wait()

        if self.failure_mode == "offline":
            raise ServerOfflineError("Simulated backend disconnect during process")

        if self.process_delay > 0:
            time.sleep(self.process_delay)

        if cancel_token and cancel_token.is_set():
            res = OCRResult(file_path=str(source))
            res.cancelled = True
            res.status = CoreJobStatus.CANCELLED
            return res

        page = PageResult(
            page_num=1,
            markdown="# Test Page\n\nExtracted content from test image.",
            latency=0.15,
            status=CoreJobStatus.SUCCESS,
            raw_json={"usage": {"total_tokens": 42}},
        )

        if progress_callback:
            progress_callback(1, 1, page)

        res = OCRResult(file_path=str(source), pages=[page])
        res.status = CoreJobStatus.SUCCESS
        return res


def test_loopback_security_middleware_host_validation(tmp_path: Path) -> None:
    """Verify loopback Host enforcement (rejects external hosts, accepts loopback)."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # Valid loopback Hosts
    status, _, _ = client.get("/health", headers={"host": "127.0.0.1"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "127.0.0.1:8000"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "localhost:3000"})
    assert status == 200

    # Rejected non-loopback Hosts
    status, _, body = client.get("/health", headers={"host": "attacker.com"})
    assert status == 400
    assert body == b"Bad Request"

    status, _, body = client.get("/health", headers={"host": "192.168.1.10:8000"})
    assert status == 400
    assert body == b"Bad Request"


def test_loopback_security_middleware_origin_validation(tmp_path: Path) -> None:
    """Verify Origin header validation on mutating requests (POST)."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # Valid loopback Origins on POST
    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert status == 404  # Passes middleware, route handles missing job

    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:5173"},
    )
    assert status == 404

    # Rejected non-loopback Origins on POST
    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://attacker.com"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "https://malicious-site.org:8080"},
    )
    assert status == 403
    assert body == b"Forbidden"


def test_upload_streaming_size_limit_rejection(tmp_path: Path) -> None:
    """Verify that uploading a file larger than max_upload_size returns 413 and deletes partial files."""
    limit = 1024  # 1 KB limit
    app = create_app(upload_dir=tmp_path, max_upload_size=limit)
    client = AsgiClient(app)

    oversized_data = b"X" * (2 * 1024)  # 2 KB
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("large_file.bin", oversized_data, "application/octet-stream")}
    )

    status, _, resp = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 413
    assert b"File exceeds upload limit" in resp

    # Ensure no lingering partial files remain in upload directory
    files_in_dir = list(tmp_path.iterdir())
    assert len(files_in_dir) == 0


def test_upload_path_traversal_protection(tmp_path: Path) -> None:
    """Verify path traversal characters in filename do not escape upload root."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes()
    traversal_name = "../../traversal_test.png"
    body, ct = urllib3.encode_multipart_formdata(
        {"file": (traversal_name, png_bytes, "image/png")}
    )

    status, _, resp = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 200
    data = json.loads(resp.decode("utf-8"))
    assert "id" in data

    # Verify written file is strictly inside tmp_path
    uploaded_files = list(tmp_path.iterdir())
    assert len(uploaded_files) == 1
    assert uploaded_files[0].resolve().is_relative_to(tmp_path.resolve())


def test_no_routes_modify_allow_remote_or_endpoint() -> None:
    """Verify that no API routes expose settings mutation or non-loopback bindings."""
    app = create_app()
    for route in app.routes:
        path = getattr(route, "path", "")
        assert "settings" not in path.lower() or "update" not in path.lower()

    # Enforce loopback check helper
    enforce_loopback_host("127.0.0.1")
    enforce_loopback_host("localhost")

    with pytest.raises(ValueError, match="strictly requires loopback"):
        enforce_loopback_host("0.0.0.0")

    with pytest.raises(ValueError, match="strictly requires loopback"):
        enforce_loopback_host("192.168.1.100")


def test_document_lifecycle_and_exports(tmp_path: Path) -> None:
    """Verify full document flow: upload -> preview -> extract -> wait -> export (MD, JSON, DOCX)."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Upload valid PNG image
    png_bytes = _create_sample_png_bytes(80, 80)
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("sample_test.png", png_bytes, "image/png")}
    )
    status, _, resp = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 200
    meta = json.loads(resp.decode("utf-8"))
    job_id = meta["id"]
    assert meta["pages"] == 1
    assert meta["filename"] == "sample_test.png"

    # 2. Preview page 1
    status, headers, preview_bytes = client.get(f"/api/documents/{job_id}/pages/1/preview")
    assert status == 200
    assert headers.get("content-type") == "image/png"
    assert len(preview_bytes) > 0

    # 3. Extract document
    status, _, _ = client.post(f"/api/documents/{job_id}/extract")
    assert status == 202

    # Wait for orchestrator worker to process
    for _ in range(50):
        job = orchestrator.get_job(job_id)
        if job and job.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)
    assert job is not None
    assert job.status == JobStatus.SUCCESS

    # 4. Export Markdown
    status, headers, md_bytes = client.get(
        f"/api/documents/{job_id}/export", query_string="format=md"
    )
    assert status == 200
    assert b"# Test Page" in md_bytes
    assert "sample_test.md" in headers.get("content-disposition", "")

    # 5. Export JSON
    status, _, json_bytes = client.get(
        f"/api/documents/{job_id}/export", query_string="format=json"
    )
    assert status == 200
    parsed_json = json.loads(json_bytes.decode("utf-8"))
    assert parsed_json["status"] == "SUCCESS"
    assert len(parsed_json["pages"]) == 1

    # 6. Export DOCX
    status, headers, docx_bytes = client.get(
        f"/api/documents/{job_id}/export", query_string="format=docx"
    )
    assert status == 200
    assert docx_bytes.startswith(b"PK")  # ZIP OpenXML header
    assert "sample_test.docx" in headers.get("content-disposition", "")

    orchestrator.stop()


def test_cancellation_mid_run(tmp_path: Path) -> None:
    """Verify cooperative cancellation sets CANCELLED status."""
    started = threading.Event()
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes()
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("cancel_test.png", png_bytes, "image/png")}
    )
    status, _, resp = client.post(
        "/api/documents", headers={"content-type": ct}, body=body
    )
    job_id = json.loads(resp.decode("utf-8"))["id"]

    # Start extract and wait until processing is guaranteed in-flight
    client.post(f"/api/documents/{job_id}/extract")
    assert started.wait(timeout=5.0), "Processing did not start within timeout"

    # Send cancel precisely while processing is in-flight
    status, _, _ = client.post(f"/api/documents/{job_id}/cancel")
    assert status == 200

    # Release gate so process_document resumes and observes cancellation
    gate.set()

    # Wait for status resolution
    for _ in range(50):
        job = orchestrator.get_job(job_id)
        if job and job.status == JobStatus.CANCELLED:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.CANCELLED
    orchestrator.stop()


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


def test_loopback_security_middleware_port_pinning(tmp_path: Path) -> None:
    """Verify port pinning rejects requests from different port origin or host."""
    app = create_app(upload_dir=tmp_path, allowed_port=8000)
    client = AsgiClient(app)

    # 1. Mutating requests (POST) from mismatched origin must be rejected with 403
    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:3000"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # 2. Mutating requests from matching pinned port origin are accepted past middleware
    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert status == 404  # Reached app route

    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:8000"},
    )
    assert status == 404

    # 3. Host header with mismatched port is rejected with 400
    status, _, body = client.get("/health", headers={"host": "localhost:3000"})
    assert status == 400
    assert body == b"Bad Request"

    status, _, body = client.get("/health", headers={"host": "127.0.0.1:9000"})
    assert status == 400
    assert body == b"Bad Request"

    # 4. Host header matching pinned port is accepted
    status, _, _ = client.get("/health", headers={"host": "127.0.0.1:8000"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "localhost:8000"})
    assert status == 200


def test_delete_document_cleans_up_file(tmp_path: Path) -> None:
    """Verify DELETE /api/documents/{id} unlinks the uploaded file and removes job."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("delete_me.png", png_bytes, "image/png")}
    )
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    job_id = json.loads(resp.decode("utf-8"))["id"]

    # Verify file was written to disk
    matching_files = list(tmp_path.glob(f"{job_id}_*"))
    assert len(matching_files) == 1
    assert matching_files[0].exists()

    # Call DELETE endpoint
    del_status, _, del_resp = client.delete(f"/api/documents/{job_id}")
    assert del_status == 200
    del_data = json.loads(del_resp.decode("utf-8"))
    assert del_data["deleted"] is True
    assert del_data["job_id"] == job_id

    # Verify file is deleted on disk
    assert not matching_files[0].exists()
    assert len(list(tmp_path.glob(f"{job_id}_*"))) == 0

    # Calling DELETE on already removed job returns 404
    del_again_status, _, _ = client.delete(f"/api/documents/{job_id}")
    assert del_again_status == 404


def test_startup_sweep_cleans_up_stale_uploads(tmp_path: Path) -> None:
    """Verify startup sweep unlinks stale upload files left from previous sessions."""
    stale1 = tmp_path / "stale1.png"
    stale2 = tmp_path / "stale2.pdf"
    stale1.write_bytes(b"stale-data-1")
    stale2.write_bytes(b"stale-data-2")
    assert stale1.exists()
    assert stale2.exists()

    app = create_app(upload_dir=tmp_path)

    async def _run():
        async with app.router.lifespan_context(app):
            # After startup sweep, stale files should be unlinked immediately
            assert not stale1.exists()
            assert not stale2.exists()

    asyncio.run(_run())
    assert len(list(tmp_path.iterdir())) == 0


def test_lifespan_cleans_up_upload_scratch(tmp_path: Path) -> None:
    """Verify FastAPI lifespan shutdown cleans up all files in upload directory."""
    app = create_app(upload_dir=tmp_path)

    async def _run_lifespan():
        async with app.router.lifespan_context(app):
            # Populate upload directory with session files during active lifecycle
            file1 = tmp_path / "session_file1.png"
            file2 = tmp_path / "session_file2.pdf"
            file1.write_bytes(b"data1")
            file2.write_bytes(b"data2")
            assert file1.exists()
            assert file2.exists()

    asyncio.run(_run_lifespan())

    # On shutdown, all files in upload directory must be deleted
    assert len(list(tmp_path.iterdir())) == 0


def test_dev_mode_permits_vite_dev_server_origin() -> None:
    """Verify dev_mode allows Vite/React dev origins while production blocks them."""
    # 1. Production mode (dev_mode=False) rejects dev server origins with 403
    prod_app = create_app(allowed_port=8000, dev_mode=False)
    prod_client = AsgiClient(prod_app)
    status, _, body = prod_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = prod_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # Verify Vite dev server proxy header combination is rejected in production
    status, _, body = prod_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"host": "127.0.0.1:8000", "origin": "http://localhost:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # 2. Dev mode (dev_mode=True) permits Vite dev server origins
    dev_app = create_app(allowed_port=8000, dev_mode=True)
    dev_client = AsgiClient(dev_app)
    status, _, _ = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:5173"},
    )
    assert status == 404  # Passes middleware and reaches route handler

    status, _, _ = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:5173"},
    )
    assert status == 404

    # Verify Vite dev server proxy header combination is accepted in dev mode
    status, _, _ = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"host": "127.0.0.1:8000", "origin": "http://localhost:5173"},
    )
    assert status == 404

    # Port 3000 is rejected with 403 even in dev mode (dropped per YAGNI)
    status, _, body = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:3000"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # Non-whitelisted port or external origin still rejected in dev mode
    status, _, body = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:9999"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://attacker.com:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"


def test_concurrent_instance_skips_startup_sweep(tmp_path: Path) -> None:
    """Verify concurrent app instance skips startup sweep when another holds .instance.lock."""
    from web.app import _acquire_instance_lock, _release_instance_lock

    active_file = tmp_path / "active_session_file.png"
    active_file.write_bytes(b"active-content")

    # Primary instance acquires lock
    lock1 = _acquire_instance_lock(tmp_path)
    try:
        app2 = create_app(upload_dir=tmp_path)

        async def _run_second():
            async with app2.router.lifespan_context(app2):
                assert app2.state.instance_lock is None
                assert active_file.exists()
                assert active_file.read_bytes() == b"active-content"

        asyncio.run(_run_second())
        assert active_file.exists()
    finally:
        _release_instance_lock(lock1)
        lock_path = tmp_path / ".instance.lock"
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass


def test_is_port_in_use() -> None:
    """Verify is_port_in_use correctly detects open vs available ports."""
    import socket
    from web.__main__ import is_port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        assert is_port_in_use("127.0.0.1", port) is True

    assert is_port_in_use("127.0.0.1", port) is False


def test_sse_events_streaming_route(tmp_path: Path) -> None:
    """Verify /api/events SSE route streams broadcast events without coroutine iteration errors."""
    mock_engine = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_engine)  # type: ignore[arg-type]
    app = create_app(engine=mock_engine, orchestrator=orchestrator, upload_dir=tmp_path)  # type: ignore[arg-type]

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
    event_received = asyncio.Event()

    async def receive() -> Dict[str, Any]:
        await event_received.wait()
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
            if b"test_event" in body:
                event_received.set()

    async def _run() -> None:
        app_task = asyncio.create_task(app(scope, receive, send))

        for _ in range(50):
            with orchestrator._lock:
                if len(orchestrator._subscribers) > 0:
                    break
            await asyncio.sleep(0.02)

        orchestrator.broadcast("test_event", {"status": "ok"})

        try:
            await asyncio.wait_for(event_received.wait(), timeout=3.0)
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
    assert "event: test_event" in full_body
    assert 'data: {"status": "ok"}' in full_body


def test_get_documents_snapshot_rehydration(tmp_path: Path) -> None:
    """Verify in-memory document state snapshot endpoint (/api/documents) across lifecycle."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Initially empty
    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    assert docs == []

    # 2. Upload document -> verify in snapshot with "Not extracted" status
    png_bytes = _create_sample_png_bytes(80, 80)
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("snapshot_test.png", png_bytes, "image/png")}
    )
    status, _, resp = client.post(
        "/api/documents", headers={"content-type": ct}, body=body
    )
    assert status == 200
    job_id = json.loads(resp.decode("utf-8"))["id"]

    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    assert len(docs) == 1
    doc = docs[0]
    assert doc["id"] == job_id
    assert doc["name"] == "snapshot_test.png"
    assert doc["status"] == "Not extracted"
    assert doc["pages"] == 1
    assert doc["processedPages"] == 0
    assert doc["extractedText"] == ""
    assert doc["pagesData"] == {}
    assert doc["docType"] == "custom-image"
    assert doc["previewImageUrl"] == f"/api/documents/{job_id}/pages/1/preview"

    # 3. Simulate progress on orchestrator -> verify Processing state, processedPages, pagesData, extractedText
    with orchestrator._lock:
        job = orchestrator.jobs[job_id]
        job.status = JobStatus.PROCESSING
        job.current_page = 1
        job.pages_data[1] = {
            "text": "Extracted text for page 1",
            "latency": 0.35,
            "tokens": 42,
            "truncated": False,
        }

    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    assert len(docs) == 1
    doc = docs[0]
    assert doc["status"] == "Processing"
    assert doc["processedPages"] == 1
    assert doc["extractedText"] == "Extracted text for page 1"
    assert "1" in doc["pagesData"]
    page_1_data = doc["pagesData"]["1"]
    assert page_1_data["pageNumber"] == 1
    assert page_1_data["text"] == "Extracted text for page 1"
    assert page_1_data["latency"] == 0.35
    assert page_1_data["tokens"] == 42
    assert page_1_data["isTruncated"] is False

    # 4. Simulate completion -> verify Done status
    with orchestrator._lock:
        job = orchestrator.jobs[job_id]
        job.status = JobStatus.SUCCESS

    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    assert len(docs) == 1
    assert docs[0]["status"] == "Done"
    assert docs[0]["processedPages"] == 1

    # 5. Simulate truncated completion -> verify Truncated status
    with orchestrator._lock:
        job = orchestrator.jobs[job_id]
        job.pages_data[1]["truncated"] = True

    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    assert docs[0]["status"] == "Truncated"

    # 6. Delete document -> verify snapshot is empty
    status, _, resp = client.delete(f"/api/documents/{job_id}")
    assert status == 200

    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    assert docs == []

    orchestrator.stop()


def test_unextracted_upload_distinguished_from_queued_during_processing(tmp_path: Path) -> None:
    """Verify newly uploaded docs remain 'Not extracted' even when another job is processing."""
    gate = threading.Event()
    started = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Upload Doc 1
    png1_bytes = _create_sample_png_bytes(50, 50)
    body1, ct1 = urllib3.encode_multipart_formdata(
        {"file": ("doc1.png", png1_bytes, "image/png")}
    )
    status, _, resp = client.post("/api/documents", headers={"content-type": ct1}, body=body1)
    assert status == 200
    doc1_id = json.loads(resp.decode("utf-8"))["id"]

    # Trigger extract on doc1, wait for worker to pick up and start processing
    status, _, _ = client.post(f"/api/documents/{doc1_id}/extract")
    assert status == 202
    assert started.wait(timeout=5.0), "MockEngine processing did not start within timeout"

    # 2. Upload Doc 2 (do NOT enqueue, remains UPLOADED)
    png2_bytes = _create_sample_png_bytes(50, 50)
    body2, ct2 = urllib3.encode_multipart_formdata(
        {"file": ("doc2.png", png2_bytes, "image/png")}
    )
    status, _, resp = client.post("/api/documents", headers={"content-type": ct2}, body=body2)
    assert status == 200
    doc2_id = json.loads(resp.decode("utf-8"))["id"]

    # 3. Call GET /api/documents while doc1 is actively processing (gated)
    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    doc_map = {d["id"]: d for d in docs}

    assert doc1_id in doc_map
    assert doc2_id in doc_map
    assert doc_map[doc1_id]["status"] == "Processing"
    assert doc_map[doc2_id]["status"] == "Not extracted"
    assert doc_map[doc2_id]["status"] != "Waiting"
    assert doc_map[doc2_id]["statusNote"] == "Ready to extract"

    # Release gate so doc1 finishes cleanly
    gate.set()

    # Wait for doc1 to complete before cleaning up
    for _ in range(50):
        j1 = orchestrator.get_job(doc1_id)
        if j1 and j1.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)

    # 4. Cleanup / Delete both docs
    status, _, _ = client.delete(f"/api/documents/{doc1_id}")
    assert status == 200
    status, _, _ = client.delete(f"/api/documents/{doc2_id}")
    assert status == 200

    orchestrator.stop()


def test_origin_check_covers_all_non_safe_methods(tmp_path: Path) -> None:
    """Verify that all non-safe methods (standard mutating and custom verbs) enforce loopback Origin check, while safe methods pass."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)
    bad_origin = {"origin": "http://evil.com"}

    # Non-safe methods must be rejected with 403
    for method in ("POST", "PUT", "DELETE", "PATCH", "CUSTOMVERB"):
        status, _, _ = client.request(method, "/api/documents", headers=bad_origin)
        assert status == 403, f"Method {method} with evil origin expected 403 but got {status}"

    # Safe methods must pass Origin validation (not 403)
    status_get, _, _ = client.request("GET", "/api/documents", headers=bad_origin)
    assert status_get == 200

    status_head, _, _ = client.request("HEAD", "/api/documents", headers=bad_origin)
    assert status_head != 403


def test_reextraction_resets_run_id_and_progress(tmp_path: Path) -> None:
    """Verify re-extracting a document creates a new run_id and wipes previous pagesData and progress."""
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Upload doc
    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("doc.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # 2. Enqueue and simulate PROCESSING with partial pages data
    status, _, _ = client.post(f"/api/documents/{doc_id}/extract")
    assert status == 202

    with orchestrator._lock:
        job = orchestrator.jobs[doc_id]
        initial_run_id = job.run_id
        job.status = JobStatus.PROCESSING
        job.current_page = 2
        job.pages_data = {
            1: {"text": "Page 1 content", "tokens": 10, "latency": 0.5, "truncated": False},
            2: {"text": "Page 2 content", "tokens": 12, "latency": 0.4, "truncated": False},
        }

    # 3. Cancel document
    status, _, _ = client.post(f"/api/documents/{doc_id}/cancel")
    assert status == 200
    with orchestrator._lock:
        orchestrator.jobs[doc_id].status = JobStatus.CANCELLED

    # 4. Enqueue again (re-extraction)
    status, _, _ = client.post(f"/api/documents/{doc_id}/extract")
    assert status == 202

    # 5. Inspect job state and snapshot
    with orchestrator._lock:
        re_job = orchestrator.jobs[doc_id]
        new_run_id = re_job.run_id
        assert new_run_id != initial_run_id
        assert re_job.current_page == 0
        assert len(re_job.pages_data) == 0

    status, _, resp = client.get("/api/documents")
    assert status == 200
    docs = json.loads(resp.decode("utf-8"))
    doc_entry = next(d for d in docs if d["id"] == doc_id)
    assert doc_entry["run_id"] == new_run_id
    assert doc_entry["runId"] == new_run_id
    assert doc_entry["processedPages"] == 0
    assert doc_entry["pagesData"] == {}

    gate.set()
    orchestrator.stop()


def test_doctor_endpoint_execution_and_schema(tmp_path: Path) -> None:
    """Verify POST /api/doctor runs diagnostics and GET /api/doctor returns the cached report."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # Before POST, GET /api/doctor returns 404 with report: None
    status, _, resp = client.get("/api/doctor")
    assert status == 404
    data = json.loads(resp.decode("utf-8"))
    assert data["report"] is None

    # POST /api/doctor executes diagnostics
    status, _, resp = client.post("/api/doctor")
    assert status == 200
    post_data = json.loads(resp.decode("utf-8"))
    assert "status" in post_data
    assert "exit_code" in post_data
    assert "total_checks" in post_data
    assert "failed_checks" in post_data
    assert "checks" in post_data
    assert isinstance(post_data["checks"], list)
    if post_data["checks"]:
        first_check = post_data["checks"][0]
        assert "category" in first_check
        assert "title" in first_check
        assert "status" in first_check
        assert "details" in first_check
        assert "remediation" in first_check
    assert "text" in post_data
    assert isinstance(post_data["text"], str)

    # GET /api/doctor returns cached report
    status, _, resp = client.get("/api/doctor")
    assert status == 200
    get_data = json.loads(resp.decode("utf-8"))
    assert get_data == post_data


def test_settings_endpoint_lifecycle_and_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify settings querying, valid patch persistence, and strict security rejecting immutable/malformed keys."""
    env_file = tmp_path / ".env"
    monkeypatch.chdir(tmp_path)

    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. GET /api/settings
    status, _, resp = client.get("/api/settings")
    assert status == 200
    settings_data = json.loads(resp.decode("utf-8"))
    assert "dpi" in settings_data
    assert "timeout" in settings_data
    assert "backend" in settings_data
    assert "auto_start_server" in settings_data

    # 2. PATCH /api/settings valid updates
    patch_body = json.dumps({"dpi": 150, "timeout": 45.0}).encode("utf-8")
    status, _, resp = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=patch_body,
    )
    assert status == 200
    res = json.loads(resp.decode("utf-8"))
    assert res["updated"] is True
    assert res["settings"]["dpi"] == 150
    assert res["settings"]["timeout"] == 45.0
    assert app.state.settings.dpi == 150
    assert app.state.settings.timeout == 45.0
    assert env_file.exists()
    saved_env = env_file.read_text(encoding="utf-8")
    assert "150" in saved_env

    # 3. PATCH immutable keys (must return 403 Forbidden)
    for immutable_key, immutable_val in [
        ("backend", "ollama"),
        ("llama_server_path", "/bin/sh"),
        ("allow_remote", True),
        ("runtime_mode", "custom"),
        ("local_endpoint", "http://remote:8080/v1"),
        ("model_repo", "evil/repo"),
        ("managed_backend_override", "cuda"),
    ]:
        body_bytes = json.dumps({immutable_key: immutable_val}).encode("utf-8")
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=body_bytes,
        )
        assert status == 403, f"Expected 403 for {immutable_key}, got {status}"

    # 4. PATCH unknown keys (must return 400 Bad Request)
    body_bytes = json.dumps({"unknown_key": "val"}).encode("utf-8")
    status, _, _ = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=body_bytes,
    )
    assert status == 400

    # 5. PATCH invalid types and ranges (must return 400 Bad Request)
    for invalid_payload in [
        {"dpi": "not_an_int"},
        {"dpi": -5},
        {"dpi": 1000},
        {"timeout": "slow"},
        {"timeout": 0.5},
        {"max_retries": -1},
        {"max_retries": 15},
        {"auto_start_server": "yes"},
    ]:
        body_bytes = json.dumps(invalid_payload).encode("utf-8")
        status, _, _ = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=body_bytes,
        )
        assert status == 400


class MockServerManager:
    """Mock ServerManager for web API testing."""

    def __init__(
        self,
        status: ServerStatus = ServerStatus.OFFLINE,
        ownership: ServerOwnership = ServerOwnership.NONE,
        message: str = "Offline",
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or Settings()
        self._status = status
        self._ownership = ownership
        self._last_message = message
        self._process = None
        self._log_buffer = ["Log line 1", "Log line 2"]
        self.start_calls = 0
        self.stop_calls = 0
        self.shutdown_calls = 0

    @property
    def status(self) -> ServerStatus:
        return self._status

    @property
    def ownership(self) -> ServerOwnership:
        return self._ownership

    def get_status_info(self) -> ServerStatusInfo:
        return ServerStatusInfo(
            status=self._status,
            ownership=self._ownership,
            message=self._last_message,
            endpoint=self.settings.local_endpoint,
            recent_logs=list(self._log_buffer),
        )

    def poll_status(self) -> ServerStatusInfo:
        return self.get_status_info()

    def start(self, **kwargs: Any) -> None:
        self.start_calls += 1
        self._status = ServerStatus.READY
        self._ownership = ServerOwnership.MANAGED
        self._last_message = "Server started"

    def stop(self) -> None:
        self.stop_calls += 1
        self._status = ServerStatus.OFFLINE
        self._ownership = ServerOwnership.NONE
        self._last_message = "Server stopped"

    def shutdown(self, timeout: Optional[float] = 2.0) -> None:
        self.shutdown_calls += 1
        self.stop()


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


def test_patch_settings_updates_server_manager_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify PATCH /api/settings updates server_manager.settings instance."""
    monkeypatch.chdir(tmp_path)
    mock_mgr = MockServerManager()
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path)
    client = AsgiClient(app)

    patch_body = json.dumps({"dpi": 240, "max_tokens": 4096}).encode("utf-8")
    status_code, _, body = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=patch_body,
    )
    assert status_code == 200
    assert mock_mgr.settings.dpi == 240
    assert mock_mgr.settings.max_tokens == 4096


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


def test_settings_patch_mid_document_does_not_mutate_inflight_document_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that patching settings while a document is extracting does not mutate the in-flight job's JobConfig."""
    monkeypatch.chdir(tmp_path)
    started = threading.Event()
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    mock_eng.settings = Settings(dpi=150, max_image_dimension=1024)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("snapshot_test.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # Start extraction
    status, _, _ = client.post(f"/api/documents/{doc_id}/extract")
    assert status == 202
    assert started.wait(timeout=5.0), "Processing did not start within timeout"

    # Document is now in-flight with initial snapshot settings (dpi=150, max_image_dimension=1024)
    # Patch settings mid-flight to new values
    patch_body = json.dumps({"dpi": 300, "max_image_dimension": 4096}).encode("utf-8")
    status, _, resp = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=patch_body,
    )
    assert status == 200

    # Release gate so extraction completes
    gate.set()

    for _ in range(50):
        job = orchestrator.get_job(doc_id)
        if job and job.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.SUCCESS

    # The in-flight job must have executed with the pre-patch snapshot config
    assert mock_eng.last_config is not None
    assert mock_eng.last_config.dpi == 150
    assert mock_eng.last_config.max_image_dimension == 1024

    orchestrator.stop()


def test_extract_endpoint_default_prompt_mode(tmp_path: Path) -> None:
    """Verify POST /api/documents/{id}/extract defaults to prompt_mode='text' when body is omitted."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("default_prompt.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # Call extract without body
    status, _, extract_resp = client.post(f"/api/documents/{doc_id}/extract")
    assert status == 202
    data = json.loads(extract_resp.decode("utf-8"))
    assert data["message"] == "Extraction queued"
    assert data["prompt_mode"] == "text"

    # Verify job prompt_mode
    job = orchestrator.get_job(doc_id)
    assert job is not None
    assert job.prompt_mode == "text"

    # Wait for execution and verify JobConfig received prompt_mode
    for _ in range(50):
        job = orchestrator.get_job(doc_id)
        if job and job.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.SUCCESS
    assert mock_eng.last_config is not None
    assert mock_eng.last_config.prompt_mode == "text"

    orchestrator.stop()


def test_extract_endpoint_custom_prompt_mode(tmp_path: Path) -> None:
    """Verify POST /api/documents/{id}/extract accepts custom prompt_mode='table'."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("table_prompt.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # Call extract with table prompt_mode
    payload = json.dumps({"prompt_mode": "table"}).encode("utf-8")
    status, _, extract_resp = client.post(
        f"/api/documents/{doc_id}/extract",
        headers={"content-type": "application/json"},
        body=payload,
    )
    assert status == 202
    data = json.loads(extract_resp.decode("utf-8"))
    assert data["message"] == "Extraction queued"
    assert data["prompt_mode"] == "table"

    job = orchestrator.get_job(doc_id)
    assert job is not None
    assert job.prompt_mode == "table"

    for _ in range(50):
        job = orchestrator.get_job(doc_id)
        if job and job.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.SUCCESS
    assert mock_eng.last_config is not None
    assert mock_eng.last_config.prompt_mode == "table"
    assert mock_eng.last_config.effective_prompt == "Table Recognition:"

    orchestrator.stop()


def test_extract_endpoint_formula_prompt_mode(tmp_path: Path) -> None:
    """Verify POST /api/documents/{id}/extract accepts prompt_mode='formula'."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("formula_prompt.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # Call extract with formula prompt_mode
    payload = json.dumps({"prompt_mode": "formula"}).encode("utf-8")
    status, _, extract_resp = client.post(
        f"/api/documents/{doc_id}/extract",
        headers={"content-type": "application/json"},
        body=payload,
    )
    assert status == 202
    data = json.loads(extract_resp.decode("utf-8"))
    assert data["message"] == "Extraction queued"
    assert data["prompt_mode"] == "formula"

    job = orchestrator.get_job(doc_id)
    assert job is not None
    assert job.prompt_mode == "formula"

    for _ in range(50):
        job = orchestrator.get_job(doc_id)
        if job and job.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.SUCCESS
    assert mock_eng.last_config is not None
    assert mock_eng.last_config.prompt_mode == "formula"
    assert mock_eng.last_config.effective_prompt == "Formula Recognition:"

    orchestrator.stop()


def test_extract_endpoint_invalid_prompt_mode(tmp_path: Path) -> None:
    """Verify POST /api/documents/{id}/extract rejects unsupported prompt_mode with 400 Bad Request."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("invalid_prompt.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # Call extract with unknown prompt_mode
    payload = json.dumps({"prompt_mode": "unknown"}).encode("utf-8")
    status, _, err_resp = client.post(
        f"/api/documents/{doc_id}/extract",
        headers={"content-type": "application/json"},
        body=payload,
    )
    assert status == 400
    err_data = json.loads(err_resp.decode("utf-8"))
    assert "Invalid prompt_mode" in err_data["detail"]
    assert "unknown" in err_data["detail"]

    # Verify job status was not changed to QUEUED or PROCESSING
    job = orchestrator.get_job(doc_id)
    assert job is not None
    assert job.status == JobStatus.UPLOADED

    orchestrator.stop()



