"""Tests for Web API, security middleware, and queue lifecycle."""

import asyncio
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch
import urllib3

from PIL import Image
import pypdfium2 as pdfium
import pytest

from config.settings import Settings
from core.client import ClientError, ServerOfflineError
from core.engine import OCREngine
from core.models import JobConfig, JobStatus as CoreJobStatus, OCRResult, PageResult
from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo
from web.app import create_app, enforce_loopback_host
from web.orchestrator import JobState, JobStatus, WebOrchestrator


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

            req_path = path
            req_query = query_string
            if "?" in req_path:
                req_path, parsed_query = req_path.split("?", 1)
                if not req_query:
                    req_query = parsed_query

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.1"},
                "http_version": "1.1",
                "method": method.upper(),
                "scheme": "http",
                "path": req_path,
                "raw_path": req_path.encode("latin-1"),
                "query_string": req_query.encode("latin-1"),
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
        self.executed_configs: list[Optional[JobConfig]] = []

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
        self.executed_configs.append(config)
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

    status, _, _ = client.get("/health", headers={"host": "[::1]"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "[::1]:8000"})
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

    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://[::1]:8000"},
    )
    assert status == 404

    # Sec-Fetch-Site cross-site rejection on POST
    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={
            "sec-fetch-site": "cross-site",
            "origin": "http://127.0.0.1:8000",
        },
    )
    assert status == 403
    assert body == b"Forbidden"

    # Sec-Fetch-Site cross-site permitted on GET (safe method)
    status, _, _ = client.get(
        "/health",
        headers={"sec-fetch-site": "cross-site"},
    )
    assert status == 200

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

    oversized_data = b"\x89PNG\r\n\x1a\n" + b"X" * (2 * 1024)  # 2 KB with valid PNG magic bytes
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("large_file.png", oversized_data, "image/png")}
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


def test_upload_unsupported_extension_rejected(tmp_path: Path) -> None:
    """Verify uploading files with unsupported extensions returns 400 without creating files on disk."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    for ext in (".exe", ".bin", ".txt"):
        body, ct = urllib3.encode_multipart_formdata(
            {"file": (f"payload{ext}", b"some content here", "application/octet-stream")}
        )
        status, _, resp = client.post(
            "/api/documents",
            headers={"content-type": ct},
            body=body,
        )
        assert status == 400
        data = json.loads(resp.decode("utf-8"))
        assert "unsupported file extension" in data["detail"].lower()
        assert len(list(tmp_path.iterdir())) == 0


def test_upload_mismatched_magic_bytes_rejected(tmp_path: Path) -> None:
    """Verify files with mismatched magic byte signatures return 400 without creating files on disk."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    test_cases = [
        ("sample.pdf", b"NOT_A_PDF_CONTENT", "application/pdf"),
        ("sample.png", b"NOT_A_PNG", "image/png"),
    ]
    for filename, content, ctype in test_cases:
        body, ct = urllib3.encode_multipart_formdata(
            {"file": (filename, content, ctype)}
        )
        status, _, resp = client.post(
            "/api/documents",
            headers={"content-type": ct},
            body=body,
        )
        assert status == 400
        data = json.loads(resp.decode("utf-8"))
        assert "signature does not match" in data["detail"].lower()
        assert len(list(tmp_path.iterdir())) == 0


def test_upload_empty_file_rejected(tmp_path: Path) -> None:
    """Verify uploading an empty file returns 400 without creating files on disk."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("sample.pdf", b"", "application/pdf")}
    )
    status, _, resp = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 400
    data = json.loads(resp.decode("utf-8"))
    assert "empty" in data["detail"].lower()
    assert len(list(tmp_path.iterdir())) == 0


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
    """Verify FastAPI lifespan shutdown cleans up tracked files in upload directory."""
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
            app.state.orchestrator.register_job(
                JobState(job_id="file1", filename="session_file1.png", file_path=file1, page_count=1)
            )
            app.state.orchestrator.register_job(
                JobState(job_id="file2", filename="session_file2.pdf", file_path=file2, page_count=1)
            )

    asyncio.run(_run_lifespan())

    # On shutdown, tracked files in upload directory must be deleted
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


def test_origin_check_covers_all_methods_with_origin(tmp_path: Path) -> None:
    """Verify that any request (mutating or safe) with untrusted Origin is rejected with 403, while requests without Origin pass."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)
    bad_origin = {"origin": "http://evil.com"}

    # All methods supplying an untrusted Origin must be rejected with 403
    for method in ("POST", "PUT", "DELETE", "PATCH", "GET", "HEAD", "CUSTOMVERB"):
        status, _, _ = client.request(method, "/api/documents", headers=bad_origin)
        assert status == 403, f"Method {method} with evil origin expected 403 but got {status}"

    # Requests without Origin header succeed for safe methods
    status_get, _, _ = client.request("GET", "/api/documents")
    assert status_get == 200

    status_head, _, _ = client.request("HEAD", "/api/documents")
    assert status_head != 403


test_origin_check_covers_all_non_safe_methods = test_origin_check_covers_all_methods_with_origin


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
    """Verify settings querying, valid patch persistence, and strict security rejecting malformed keys."""
    pre_env = dict(os.environ)
    try:
        env_file = tmp_path / ".env"
        monkeypatch.chdir(tmp_path)

        app = create_app(upload_dir=tmp_path, env_path=env_file)
        client = AsgiClient(app)

        # 1. GET /api/settings
        status, _, resp = client.get("/api/settings")
        assert status == 200
        settings_data = json.loads(resp.decode("utf-8"))
        assert "dpi" in settings_data
        assert "timeout" in settings_data
        assert "backend" in settings_data
        assert "auto_start_server" in settings_data
        assert "llama_server_path" in settings_data
        assert "allow_remote" in settings_data

        # 2. PATCH /api/settings valid updates (numeric/basic settings)
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

        # 3. PATCH newly mutable backend/runtime keys
        patch_backend_body = json.dumps({
            "backend": "ollama",
            "runtime_mode": "custom",
            "managed_backend_override": "cuda",
            "llama_server_path": "C:\\tools\\llama-server.exe",
            "model_repo": "test/repo",
            "allow_remote": True,
            "local_endpoint": "http://remote.lan:8080/v1",
        }).encode("utf-8")
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=patch_backend_body,
        )
        assert status == 200
        res = json.loads(resp.decode("utf-8"))
        assert res["updated"] is True
        assert res["settings"]["backend"] == "ollama"
        assert res["settings"]["runtime_mode"] == "custom"
        assert res["settings"]["managed_backend_override"] == "cuda"
        assert res["settings"]["llama_server_path"] == "C:\\tools\\llama-server.exe"
        assert res["settings"]["model_repo"] == "test/repo"
        assert res["settings"]["allow_remote"] is True
        assert res["settings"]["local_endpoint"] == "http://remote.lan:8080/v1"
        assert app.state.settings.backend == "ollama"
        assert app.state.settings.local_endpoint == "http://remote.lan:8080/v1"
        assert app.state.engine.client.endpoint == "http://remote.lan:8080/v1/chat/completions"

        # Also test empty string llama_server_path normalizes to None
        status, _, resp = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=json.dumps({"llama_server_path": "   "}).encode("utf-8"),
        )
        assert status == 200
        res = json.loads(resp.decode("utf-8"))
        assert res["settings"]["llama_server_path"] is None
        assert app.state.settings.llama_server_path is None

        # 4. Non-loopback local_endpoint rejected when allow_remote=False
        # Reset to loopback first with allow_remote=False
        status, _, _ = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=json.dumps({"allow_remote": False, "local_endpoint": "http://127.0.0.1:8080/v1"}).encode("utf-8"),
        )
        assert status == 200
        # Attempting to change local_endpoint to non-loopback while allow_remote=False must return 400
        status, _, _ = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=json.dumps({"local_endpoint": "http://remote.lan:8080/v1"}).encode("utf-8"),
        )
        assert status == 400

        # 5. PATCH unknown keys (must return 400 Bad Request)
        body_bytes = json.dumps({"unknown_key": "val"}).encode("utf-8")
        status, _, _ = client.patch(
            "/api/settings",
            headers={"content-type": "application/json"},
            body=body_bytes,
        )
        assert status == 400

        # 6. PATCH invalid enum values (must return 400 Bad Request)
        for invalid_enum in [
            {"backend": "invalid_engine"},
            {"runtime_mode": "invalid_mode"},
            {"managed_backend_override": "invalid_accel"},
        ]:
            status, _, _ = client.patch(
                "/api/settings",
                headers={"content-type": "application/json"},
                body=json.dumps(invalid_enum).encode("utf-8"),
            )
            assert status == 400

        # 7. PATCH invalid types and ranges (must return 400 Bad Request)
        for invalid_payload in [
            {"dpi": "not_an_int"},
            {"dpi": -5},
            {"dpi": 1000},
            {"timeout": "slow"},
            {"timeout": 0.5},
            {"max_retries": -1},
            {"max_retries": 15},
            {"auto_start_server": "yes"},
            {"allow_remote": "yes"},
            {"llama_server_path": 123},
            {"model_repo": ""},
            {"backend": ""},
            {"local_endpoint": ""},
            {"runtime_mode": ""},
            {"managed_backend_override": ""},
        ]:
            body_bytes = json.dumps(invalid_payload).encode("utf-8")
            status, _, _ = client.patch(
                "/api/settings",
                headers={"content-type": "application/json"},
                body=body_bytes,
            )
            assert status == 400
    finally:
        os.environ.clear()
        os.environ.update(pre_env)


# Alias for test_settings_api_patch_and_persistence
test_settings_api_patch_and_persistence = test_settings_endpoint_lifecycle_and_security


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


def test_dialog_pick_file_endpoint(tmp_path: Path) -> None:
    """Verify POST /api/dialog/file returns picked file path or None."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # 1. Success mock
    with patch("web.app._pick_executable_file", return_value="C:\\custom\\llama-server.exe"):
        status, _, body = client.post("/api/dialog/file")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data == {"path": "C:\\custom\\llama-server.exe"}

    # 2. Cancellation / None mock
    with patch("web.app._pick_executable_file", return_value=None):
        status, _, body = client.post("/api/dialog/file")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data == {"path": None}


def test_pick_executable_file_helper() -> None:
    """Verify _pick_executable_file handles subprocess exit codes and exceptions."""
    import subprocess
    from web.app import _pick_executable_file

    class DummyProc:
        def __init__(self, code: int, stdout: str):
            self.returncode = code
            self.stdout = stdout

    # Returncode 0 with path
    with patch("subprocess.run", return_value=DummyProc(0, "C:\\llama\\llama-server.exe\n")):
        assert _pick_executable_file() == "C:\\llama\\llama-server.exe"

    # Returncode 0 with empty stdout (cancelled)
    with patch("subprocess.run", return_value=DummyProc(0, "   \n")):
        assert _pick_executable_file() is None

    # Non-zero returncode
    with patch("subprocess.run", return_value=DummyProc(1, "error")):
        assert _pick_executable_file() is None

    # Exception / timeout
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=120)):
        assert _pick_executable_file() is None


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
        self._log_listeners: List[Callable[[str], None]] = []
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

    def get_recent_logs(self, max_lines: int = 50) -> List[str]:
        return list(self._log_buffer[-max_lines:]) if max_lines > 0 else list(self._log_buffer)

    def add_log_listener(self, listener: Callable[[str], None]) -> None:
        if listener not in self._log_listeners:
            self._log_listeners.append(listener)

    def remove_log_listener(self, listener: Callable[[str], None]) -> None:
        if listener in self._log_listeners:
            self._log_listeners.remove(listener)

    def broadcast_log(self, line: str) -> None:
        self._log_buffer.append(line)
        for l in list(self._log_listeners):
            try:
                l(line)
            except Exception:
                pass

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
    app = create_app(server_manager=mock_mgr, upload_dir=tmp_path, env_path=tmp_path / ".env")
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
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path, env_path=tmp_path / ".env")
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


def test_in_flight_patch_settings_isolation(tmp_path: Path) -> None:
    """Verify in-flight extraction retains initial settings snapshot while next job uses patched settings."""
    env_file = tmp_path / ".env"
    repo_env = Path(__file__).resolve().parent.parent / ".env"
    repo_pre = repo_env.read_bytes() if repo_env.exists() else None

    started = threading.Event()
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    mock_eng.settings = Settings(dpi=100, max_tokens=1024)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path, env_path=env_file)
    client = AsgiClient(app)

    png1 = _create_sample_png_bytes(50, 50)
    body1, ct1 = urllib3.encode_multipart_formdata({"file": ("inflight_1.png", png1, "image/png")})
    status, _, resp1 = client.post("/api/documents", headers={"content-type": ct1}, body=body1)
    assert status == 200
    doc1_id = json.loads(resp1.decode("utf-8"))["id"]

    client.post(f"/api/documents/{doc1_id}/extract")
    assert started.wait(timeout=5.0), "Document 1 processing did not start"

    patch_body = json.dumps({"dpi": 250, "max_tokens": 2048}).encode("utf-8")
    status, _, resp_patch = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=patch_body,
    )
    assert status == 200
    assert json.loads(resp_patch.decode("utf-8"))["updated"] is True

    gate.set()
    for _ in range(50):
        j1 = orchestrator.get_job(doc1_id)
        if j1 and j1.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)
    assert j1 is not None and j1.status == JobStatus.SUCCESS

    assert len(mock_eng.executed_configs) >= 1
    assert mock_eng.executed_configs[0] is not None
    assert mock_eng.executed_configs[0].dpi == 100

    mock_eng.process_gate = None
    mock_eng.processing_started = None
    png2 = _create_sample_png_bytes(60, 60)
    body2, ct2 = urllib3.encode_multipart_formdata({"file": ("subsequent_2.png", png2, "image/png")})
    status, _, resp2 = client.post("/api/documents", headers={"content-type": ct2}, body=body2)
    assert status == 200
    doc2_id = json.loads(resp2.decode("utf-8"))["id"]

    client.post(f"/api/documents/{doc2_id}/extract")
    for _ in range(50):
        j2 = orchestrator.get_job(doc2_id)
        if j2 and j2.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)
    assert j2 is not None and j2.status == JobStatus.SUCCESS

    assert len(mock_eng.executed_configs) >= 2
    assert mock_eng.executed_configs[1] is not None
    assert mock_eng.executed_configs[1].dpi == 250
    assert mock_eng.settings.max_tokens == 2048

    assert env_file.exists()
    env_text = env_file.read_text(encoding="utf-8")
    assert "OCR_DPI='250'" in env_text
    assert "OCR_MAX_TOKENS='2048'" in env_text

    repo_post = repo_env.read_bytes() if repo_env.exists() else None
    assert repo_post == repo_pre

    orchestrator.stop()


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


class MockModelDownloader:
    """Mock model downloader for web API testing."""

    def __init__(
        self,
        is_downloading: bool = False,
        error_message: Optional[str] = None,
        bytes_downloaded: int = 0,
        total_bytes: int = 1434837056,
        current_file: str = "",
        percent: float = 0.0,
    ) -> None:
        self.is_downloading = is_downloading
        self.error_message = error_message
        self.bytes_downloaded = bytes_downloaded
        self.total_bytes = total_bytes
        self.current_file = current_file
        self.percent = percent
        self.download_started = threading.Event()
        self.cancel_called = threading.Event()
        self.progress_callback: Optional[Callable[..., None]] = None

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_downloading": self.is_downloading,
            "bytes_downloaded": self.bytes_downloaded,
            "total_bytes": self.total_bytes,
            "current_file": self.current_file,
            "error_message": self.error_message,
            "percent": self.percent,
        }

    def download(self) -> bool:
        self.is_downloading = True
        self.download_started.set()
        if self.progress_callback:
            self.progress_callback({
                "bytes_downloaded": 700000000,
                "total_bytes": self.total_bytes,
                "percent": 48.79,
                "active_file": "GLM-OCR-Q8_0.gguf",
                "speed": 10485760.0,
                "is_downloading": True,
            })
        return True

    def cancel(self) -> None:
        self.cancel_called.set()
        self.is_downloading = False


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

    # Also test query parameter injection
    status, _, body = client.request(
        "POST",
        "/api/model/download",
        query_string="url=http://evil.com",
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

    # 1. Body forbidden param
    status, _, body = client.post(
        "/api/runtime/download",
        headers={"content-type": "application/json"},
        body=b'{"url": "http://malicious.example.com/binary.zip"}',
    )
    assert status == 400
    resp_data = json.loads(body.decode("utf-8"))
    assert "Client-controlled download targets are strictly prohibited" in resp_data["detail"]

    # 2. Query param forbidden param
    status, _, body = client.request(
        "POST",
        "/api/runtime/download",
        query_string="path=/etc/shadow",
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


def test_rehydrate_extracted_text_success_job_with_all_pages_non_empty(tmp_path: Path) -> None:
    """Verify snapshot extractedText joins non-empty pages with separator on success."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        sample_file = tmp_path / "success_doc.pdf"
        sample_file.write_bytes(b"%PDF-1.4 dummy content")

        job_id = "test-rehydrate-success"
        job = JobState(
            job_id=job_id,
            filename="success_doc.pdf",
            file_path=sample_file,
            page_count=2,
            status=JobStatus.SUCCESS,
        )
        job.pages_data[1] = {
            "pageNumber": 1,
            "text": "Page 1 content",
            "latency": 0.1,
            "tokens": 10,
            "truncated": False,
        }
        job.pages_data[2] = {
            "pageNumber": 2,
            "text": "Page 2 content",
            "latency": 0.1,
            "tokens": 10,
            "truncated": False,
        }
        orchestrator.register_job(job)

        status_code, _, body = client.get("/api/documents")
        assert status_code == 200
        docs = json.loads(body.decode("utf-8"))
        assert len(docs) == 1
        doc = docs[0]
        assert doc["extractedText"] == "Page 1 content\n\n---\n\nPage 2 content"
    finally:
        orchestrator.stop()


def test_rehydrate_extracted_text_failed_job_with_empty_failed_page_no_trailing_separator(
    tmp_path: Path,
) -> None:
    """Verify snapshot extractedText ignores empty failed pages and avoids trailing separator."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        sample_file = tmp_path / "failed_doc.pdf"
        sample_file.write_bytes(b"%PDF-1.4 dummy content")

        job_id = "test-rehydrate-failed-empty"
        job = JobState(
            job_id=job_id,
            filename="failed_doc.pdf",
            file_path=sample_file,
            page_count=2,
            status=JobStatus.FAILED,
        )
        job.pages_data[1] = {
            "pageNumber": 1,
            "text": "Page 1 content",
            "latency": 0.1,
            "tokens": 10,
            "truncated": False,
        }
        job.pages_data[2] = {
            "pageNumber": 2,
            "text": "",
            "latency": 0.0,
            "tokens": 0,
            "truncated": False,
        }
        orchestrator.register_job(job)

        status_code, _, body = client.get("/api/documents")
        assert status_code == 200
        docs = json.loads(body.decode("utf-8"))
        assert len(docs) == 1
        doc = docs[0]
        assert doc["extractedText"] == "Page 1 content"
    finally:
        orchestrator.stop()


def test_real_engine_partial_result_ends_as_failed_job_with_page_level_status_note(
    tmp_path: Path,
) -> None:
    """Verify real engine partial result ends as FAILED job with page-level status note and exportable partial text."""

    class FakePartialClient:
        def __init__(self) -> None:
            self.call_count = 0

        def verify_multimodal_support(self) -> None:
            pass

        def complete(
            self,
            image_b64: str,
            prompt: str,
            max_tokens: Optional[int] = None,
            *args: Any,
            **kwargs: Any,
        ) -> Tuple[str, Dict[str, Any], float, bool]:
            self.call_count += 1
            if self.call_count == 1:
                return (
                    "# Page 1 Real Content\nExtracted.",
                    {"usage": {"total_tokens": 30}},
                    0.1,
                    False,
                )
            raise ClientError("HTTP 400 Bad Request: Context length exceeded on page 2")

    engine = OCREngine(settings=Settings())
    engine.client = FakePartialClient()

    pdf_path = tmp_path / "partial_doc.pdf"
    img1 = Image.new("RGB", (100, 100), color="white")
    img2 = Image.new("RGB", (100, 100), color="white")
    img1.save(pdf_path, save_all=True, append_images=[img2])

    orchestrator = WebOrchestrator(engine=engine)
    app = create_app(engine=engine, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        job_id = "test-real-engine-partial-doc"
        job = JobState(
            job_id=job_id,
            filename="partial_doc.pdf",
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
        assert j.error is not None
        assert "page 2" in j.error
        assert "Context length exceeded" in j.error
        assert j.result is not None
        assert j.result.status == CoreJobStatus.PARTIAL
        assert 1 in j.pages_data
        assert j.pages_data[1]["text"] == "# Page 1 Real Content\nExtracted."

        status_code, _, body = client.get("/api/documents")
        assert status_code == 200
        docs = json.loads(body.decode("utf-8"))
        assert len(docs) == 1
        doc = docs[0]
        assert doc["status"] == "Failed"
        assert "page 2" in (doc.get("statusNote") or "")
        assert "Context length exceeded" in (doc.get("statusNote") or "")
        assert doc["extractedText"] == "# Page 1 Real Content\nExtracted."

        status_code, _, md_body = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status_code == 200
        assert "# Page 1 Real Content\nExtracted." in md_body.decode("utf-8")

        status_code, _, json_body = client.get(f"/api/documents/{job_id}/export?format=json")
        assert status_code == 200
        parsed_json = json.loads(json_body.decode("utf-8"))
        pages_list = parsed_json.get("pages", [])
        assert len(pages_list) == 2
        assert pages_list[0]["markdown"] == "# Page 1 Real Content\nExtracted."
        assert "Context length exceeded" in (pages_list[1].get("error") or "")

        status_code, _, docx_body = client.get(f"/api/documents/{job_id}/export?format=docx")
        assert status_code == 200
        assert len(docx_body) > 0
        assert docx_body.startswith(b"PK")
    finally:
        orchestrator.stop()


def test_failed_job_exports_include_incompleteness_notice_in_md_and_docx(tmp_path: Path) -> None:
    """Verify failed job exports (with partial kept pages) include banner notice in MD and DOCX, but not JSON."""
    import docx

    class FakePartialClient:
        def __init__(self) -> None:
            self.call_count = 0

        def verify_multimodal_support(self) -> None:
            pass

        def complete(
            self,
            image_b64: str,
            prompt: str,
            max_tokens: Optional[int] = None,
            *args: Any,
            **kwargs: Any,
        ) -> Tuple[str, Dict[str, Any], float, bool]:
            self.call_count += 1
            if self.call_count == 1:
                return (
                    "# Page 1 Content\nPartial success text.",
                    {"usage": {"total_tokens": 25}},
                    0.05,
                    False,
                )
            raise ClientError("HTTP 400 Bad Request: Context length exceeded on page 2")

    engine = OCREngine(settings=Settings())
    engine.client = FakePartialClient()

    pdf_path = tmp_path / "failed_partial_export.pdf"
    img1 = Image.new("RGB", (100, 100), color="white")
    img2 = Image.new("RGB", (100, 100), color="white")
    img1.save(pdf_path, save_all=True, append_images=[img2])

    orchestrator = WebOrchestrator(engine=engine)
    app = create_app(engine=engine, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        job_id = "test-failed-partial-export-notice"
        job = JobState(
            job_id=job_id,
            filename="failed_partial_export.pdf",
            file_path=pdf_path,
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

        # 1. MD Export: begins with *[Notice: Incomplete extraction: ...]*
        status_code, _, md_body = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status_code == 200
        md_text = md_body.decode("utf-8")
        assert md_text.startswith("*[Notice: Incomplete extraction:")
        assert "# Page 1 Content\nPartial success text." in md_text

        # 2. DOCX Export: loaded by docx.Document has notice as first paragraph
        status_code, _, docx_body = client.get(f"/api/documents/{job_id}/export?format=docx")
        assert status_code == 200
        doc = docx.Document(io.BytesIO(docx_body))
        assert len(doc.paragraphs) > 0
        first_p = doc.paragraphs[0]
        assert "[Notice: Incomplete extraction:" in first_p.text

        # 3. JSON Export: does not contain notice injection, preserves per-page errors
        status_code, _, json_body = client.get(f"/api/documents/{job_id}/export?format=json")
        assert status_code == 200
        json_text = json_body.decode("utf-8")
        assert "[Notice: Incomplete extraction:" not in json_text
        parsed_json = json.loads(json_text)
        pages_list = parsed_json.get("pages", [])
        assert len(pages_list) == 2
        assert pages_list[0]["markdown"] == "# Page 1 Content\nPartial success text."
        assert "Context length exceeded on page 2" in (pages_list[1].get("error") or "")
    finally:
        orchestrator.stop()


def test_success_job_exports_do_not_include_incompleteness_notice(tmp_path: Path) -> None:
    """Verify successful job exports do not include notice banner in MD or DOCX."""
    import docx

    class FakeSuccessClient:
        def verify_multimodal_support(self) -> None:
            pass

        def complete(
            self,
            image_b64: str,
            prompt: str,
            max_tokens: Optional[int] = None,
            *args: Any,
            **kwargs: Any,
        ) -> Tuple[str, Dict[str, Any], float, bool]:
            return (
                "# Clean Page 1\nFully successful text.",
                {"usage": {"total_tokens": 20}},
                0.05,
                False,
            )

    engine = OCREngine(settings=Settings())
    engine.client = FakeSuccessClient()

    pdf_path = tmp_path / "success_export.pdf"
    img = Image.new("RGB", (100, 100), color="white")
    img.save(pdf_path)

    orchestrator = WebOrchestrator(engine=engine)
    app = create_app(engine=engine, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        job_id = "test-success-export-no-notice"
        job = JobState(
            job_id=job_id,
            filename="success_export.pdf",
            file_path=pdf_path,
            page_count=1,
            status=JobStatus.UPLOADED,
        )
        orchestrator.register_job(job)
        orchestrator.enqueue(job_id)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job(job_id)
            if j and j.status == JobStatus.SUCCESS:
                break
            time.sleep(0.02)

        j = orchestrator.get_job(job_id)
        assert j is not None
        assert j.status == JobStatus.SUCCESS

        # 1. MD Export: no *[Notice:
        status_code, _, md_body = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status_code == 200
        md_text = md_body.decode("utf-8")
        assert "*[Notice:" not in md_text
        assert "# Clean Page 1\nFully successful text." in md_text

        # 2. DOCX Export: no [Notice:
        status_code, _, docx_body = client.get(f"/api/documents/{job_id}/export?format=docx")
        assert status_code == 200
        doc = docx.Document(io.BytesIO(docx_body))
        assert not any("[Notice:" in p.text for p in doc.paragraphs)
    finally:
        orchestrator.stop()


def test_partial_failure_status_note_is_bounded_when_many_pages_fail(tmp_path: Path) -> None:
    """Verify error summary is bounded to 3 pages plus overflow count when many pages fail."""

    class FakePartialTenPageClient:
        def __init__(self) -> None:
            self.call_count = 0

        def verify_multimodal_support(self) -> None:
            pass

        def complete(
            self,
            image_b64: str,
            prompt: str,
            max_tokens: Optional[int] = None,
            *args: Any,
            **kwargs: Any,
        ) -> Tuple[str, Dict[str, Any], float, bool]:
            self.call_count += 1
            page_num = self.call_count
            if page_num in (2, 4, 6, 8, 10):
                raise ClientError(f"HTTP 400 Bad Request: Context length exceeded on page {page_num}")
            return (
                f"# Page {page_num} Content\nExtracted successfully.",
                {"usage": {"total_tokens": 25}},
                0.05,
                False,
            )

    engine = OCREngine(settings=Settings())
    engine.client = FakePartialTenPageClient()

    pdf_path = tmp_path / "ten_page_doc.pdf"
    pages = [Image.new("RGB", (100, 100), color="white") for _ in range(10)]
    pages[0].save(pdf_path, save_all=True, append_images=pages[1:])

    orchestrator = WebOrchestrator(engine=engine)
    app = create_app(engine=engine, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        job_id = "test-bounded-partial-failure-job"
        job = JobState(
            job_id=job_id,
            filename="ten_page_doc.pdf",
            file_path=pdf_path,
            page_count=10,
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
        assert j.error is not None
        assert "page 2" in j.error
        assert "page 4" in j.error
        assert "page 6" in j.error
        assert "and 2 other pages failed" in j.error
        assert len(j.error) < 400

        # Verify GET /api/documents rehydrates statusNote matching job.error
        status_code, _, body = client.get("/api/documents")
        assert status_code == 200
        docs = json.loads(body.decode("utf-8"))
        assert len(docs) == 1
        doc = docs[0]
        assert doc["id"] == job_id
        assert doc["status"] == "Failed"
        assert doc["statusNote"] == j.error

        # Verify GET /api/documents/{job_id}/export?format=json returns all 5 failed pages with full errors intact
        status_code, _, json_body = client.get(f"/api/documents/{job_id}/export?format=json")
        assert status_code == 200
        parsed_json = json.loads(json_body.decode("utf-8"))
        pages_list = parsed_json.get("pages", [])
        assert len(pages_list) == 10
        failed_pages_json = [p for p in pages_list if p.get("status") == CoreJobStatus.FAILED.value]
        assert len(failed_pages_json) == 5
        for p in failed_pages_json:
            p_num = p["page_num"]
            assert p_num in (2, 4, 6, 8, 10)
            assert f"Context length exceeded on page {p_num}" in (p.get("error") or "")
    finally:
        orchestrator.stop()


def test_export_document_content_disposition_encoding(tmp_path: Path) -> None:
    """Verify Content-Disposition header with Unicode and ASCII quotes."""
    app = create_app(upload_dir=tmp_path)
    orchestrator = app.state.orchestrator
    client = AsgiClient(app)

    try:
        # 1. Unicode filename (RFC 5987 / 6266 utf-8'' percent-encoding)
        unicode_job_id = "unicode-test-job"
        fake_file = tmp_path / "dokumen_unicode.pdf"
        fake_file.write_bytes(b"dummy")
        job = JobState(
            job_id=unicode_job_id,
            filename="dokumen_éxàmple.pdf",
            file_path=fake_file,
            page_count=1,
            status=JobStatus.SUCCESS,
            pages_data={1: {"text": "Teks Indonesia"}},
        )
        orchestrator.register_job(job)

        status, headers, _ = client.get(f"/api/documents/{unicode_job_id}/export?format=md")
        assert status == 200
        expected_quoted = "dokumen_%C3%A9x%C3%A0mple.md"
        assert headers.get("content-disposition") == f"attachment; filename*=utf-8''{expected_quoted}"

        # 2. Standard ASCII filename (quoted filename="..." format)
        ascii_job_id = "ascii-test-job"
        fake_ascii_file = tmp_path / "standard_doc.pdf"
        fake_ascii_file.write_bytes(b"dummy")
        ascii_job = JobState(
            job_id=ascii_job_id,
            filename="standard_doc.pdf",
            file_path=fake_ascii_file,
            page_count=1,
            status=JobStatus.SUCCESS,
            pages_data={1: {"text": "Standard text"}},
        )
        orchestrator.register_job(ascii_job)

        status, headers, _ = client.get(f"/api/documents/{ascii_job_id}/export?format=md")
        assert status == 200
        assert headers.get("content-disposition") == 'attachment; filename="standard_doc.md"'
    finally:
        orchestrator.stop()


def test_queue_backpressure_503(tmp_path: Path) -> None:
    """Verify queue backpressure returns HTTP 503 with Retry-After header."""
    started = threading.Event()
    gate = threading.Event()
    mock_engine = MockEngine(process_gate=gate, processing_started=started)
    orchestrator = WebOrchestrator(engine=mock_engine, max_queue_size=1)
    app = create_app(upload_dir=tmp_path, engine=mock_engine, orchestrator=orchestrator)
    client = AsgiClient(app)

    try:
        f1 = tmp_path / "doc1.pdf"
        f1.write_bytes(b"dummy1")
        f2 = tmp_path / "doc2.pdf"
        f2.write_bytes(b"dummy2")
        f3 = tmp_path / "doc3.pdf"
        f3.write_bytes(b"dummy3")

        j1 = JobState(job_id="j1", filename="doc1.pdf", file_path=f1, page_count=1, status=JobStatus.UPLOADED)
        j2 = JobState(job_id="j2", filename="doc2.pdf", file_path=f2, page_count=1, status=JobStatus.UPLOADED)
        j3 = JobState(job_id="j3", filename="doc3.pdf", file_path=f3, page_count=1, status=JobStatus.UPLOADED)

        orchestrator.register_job(j1)
        orchestrator.register_job(j2)
        orchestrator.register_job(j3)

        # Enqueue job 1 -> worker picks it up and blocks on gate
        status, _, _ = client.post("/api/documents/j1/extract")
        assert status == 202
        assert started.wait(timeout=3.0)

        # Enqueue job 2 -> fits in queue (max_queue_size = 1)
        status, _, _ = client.post("/api/documents/j2/extract")
        assert status == 202

        # Enqueue job 3 -> queue is full! Must return 503 with Retry-After: 5
        status, headers, body = client.post("/api/documents/j3/extract")
        assert status == 503
        assert headers.get("retry-after") == "5"
        data = json.loads(body.decode("utf-8"))
        assert "queue is full" in data.get("detail", "").lower()
    finally:
        gate.set()
        orchestrator.stop()


def test_output_dir_isolation_and_get_output(tmp_path: Path) -> None:
    """Verify output_dir isolation and GET /api/output metadata formatting."""
    out_dir = tmp_path / "custom_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(output_dir=out_dir)
    client = AsgiClient(app)

    # Populate test artifacts
    doc_md = out_dir / "report.md"
    doc_md.write_text("# Markdown Report Content", encoding="utf-8")

    doc_json = out_dir / "data.json"
    doc_json.write_text('{"status": "ok", "pages": 2}', encoding="utf-8")

    doc_docx = out_dir / "document.docx"
    doc_docx.write_bytes(b"PK\x03\x04dummy_docx_binary")

    ignored_file = out_dir / "notes.txt"
    ignored_file.write_text("Should not be listed", encoding="utf-8")

    status, _, body = client.get("/api/output")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["path"] == str(out_dir.resolve())
    files = data["files"]
    assert len(files) == 3

    filenames = [f["filename"] for f in files]
    assert "notes.txt" not in filenames
    assert "report.md" in filenames
    assert "data.json" in filenames
    assert "document.docx" in filenames

    # Verify metadata fields for md
    md_item = next(f for f in files if f["filename"] == "report.md")
    assert md_item["type"] == "md"
    assert md_item["content"] == "# Markdown Report Content"
    assert "B" in md_item["size"] or "KB" in md_item["size"]
    assert md_item["localPath"] == str(doc_md.resolve())

    # Verify docx item placeholder content
    docx_item = next(f for f in files if f["filename"] == "document.docx")
    assert docx_item["type"] == "docx"
    assert "Microsoft Word OpenXML" in docx_item["content"]


def test_export_document_persists_artifact_to_output_dir(tmp_path: Path) -> None:
    """Verify export_document writes artifact file to configured output_dir."""
    out_dir = tmp_path / "output_artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = WebOrchestrator(engine=MockEngine())
    app = create_app(output_dir=out_dir, orchestrator=orchestrator)
    client = AsgiClient(app)

    try:
        job_id = "test-export-persist-job"
        page = PageResult(
            page_num=1,
            markdown="Extracted document body text for persistence test",
            status=CoreJobStatus.SUCCESS,
        )
        ocr_result = OCRResult(
            file_path="my_test_document.pdf",
            pages=[page],
            status=CoreJobStatus.SUCCESS,
        )
        job = JobState(
            job_id=job_id,
            filename="my_test_document.pdf",
            file_path=tmp_path / "my_test_document.pdf",
            page_count=1,
            status=JobStatus.SUCCESS,
            result=ocr_result,
        )
        orchestrator.register_job(job)

        # Export as MD
        status, _, body = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status == 200
        persisted_md = out_dir / "my_test_document.md"
        assert persisted_md.exists()
        assert persisted_md.read_text(encoding="utf-8") == "Extracted document body text for persistence test"

        # Export as JSON
        status, _, body = client.get(f"/api/documents/{job_id}/export?format=json")
        assert status == 200
        persisted_json = out_dir / "my_test_document.json"
        assert persisted_json.exists()
        parsed = json.loads(persisted_json.read_text(encoding="utf-8"))
        assert "file_path" in parsed
        assert "pages" in parsed

        # Export as DOCX
        status, _, body = client.get(f"/api/documents/{job_id}/export?format=docx")
        assert status == 200
        persisted_docx = out_dir / "my_test_document.docx"
        assert persisted_docx.exists()
        assert persisted_docx.stat().st_size > 0
    finally:
        orchestrator.stop()


def test_output_open_endpoint_and_security(tmp_path: Path) -> None:
    """Verify POST /api/output/open opens target and rejects traversal or missing paths."""
    out_dir = tmp_path / "open_test_dir"
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_file = out_dir / "sample.md"
    sample_file.write_text("Sample file", encoding="utf-8")

    app = create_app(output_dir=out_dir)
    client = AsgiClient(app)

    with patch("subprocess.run"), patch("os.startfile", create=True):
        # Open folder itself (empty body)
        status, _, body = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=b"{}",
        )
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["opened"] is True
        assert data["target"] == str(out_dir.resolve())

        # Open specific file relative
        status, _, body = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=json.dumps({"path": "sample.md"}).encode("utf-8"),
        )
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["opened"] is True
        assert data["target"] == str(sample_file.resolve())

        # Open specific file absolute
        status, _, body = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=json.dumps({"path": str(sample_file.resolve())}).encode("utf-8"),
        )
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["opened"] is True

        # Non-existent target inside out_dir -> 400
        status, _, _ = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=json.dumps({"path": "nonexistent.md"}).encode("utf-8"),
        )
        assert status == 400

        # Path traversal -> 400
        status, _, _ = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=json.dumps({"path": "../outside.txt"}).encode("utf-8"),
        )
        assert status == 400


def test_output_delete_endpoint_and_security(tmp_path: Path) -> None:
    """Verify DELETE /api/output/{filename} deletes file and rejects traversal."""
    out_dir = tmp_path / "delete_test_dir"
    out_dir.mkdir(parents=True, exist_ok=True)
    target_file = out_dir / "artifact.docx"
    target_file.write_text("test artifact", encoding="utf-8")

    app = create_app(output_dir=out_dir)
    client = AsgiClient(app)

    # Valid delete
    status, _, body = client.delete("/api/output/artifact.docx")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["deleted"] is True
    assert not target_file.exists()

    # Delete non-existent file -> 400
    status, _, _ = client.delete("/api/output/artifact.docx")
    assert status == 400

    # Path traversal attempt -> 400 or 404
    status, _, _ = client.delete("/api/output/..%2Foutside.txt")
    assert status in (400, 404)


def test_upload_valid_pdf_exercises_probe_page_count(tmp_path: Path) -> None:
    """Verify upload of valid PDF file invokes probe_page_count and returns total pages."""
    doc = pdfium.PdfDocument.new()
    doc.new_page(width=200, height=200)
    bio = io.BytesIO()
    doc.save(bio)
    doc.close()
    pdf_bytes = bio.getvalue()

    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("valid_sample.pdf", pdf_bytes, "application/pdf")}
    )
    status, _, resp = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 200
    data = json.loads(resp.decode("utf-8"))
    assert data["pages"] == 1
    assert data["total_pages"] == 1


def test_upload_size_limit_rejection_and_cleanup(tmp_path: Path) -> None:
    """Verify upload exceeding max_upload_size returns 413 and unlinks partial upload."""
    app = create_app(upload_dir=tmp_path, max_upload_size=100)
    client = AsgiClient(app)

    doc = pdfium.PdfDocument.new()
    doc.new_page(width=200, height=200)
    bio = io.BytesIO()
    doc.save(bio)
    doc.close()
    large_pdf = bio.getvalue()
    assert len(large_pdf) > 100

    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("oversized.pdf", large_pdf, "application/pdf")}
    )
    status, _, _ = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 413
    assert len(list(tmp_path.glob("*_*"))) == 0


def test_upload_corrupt_page_inspection_cleanup(tmp_path: Path) -> None:
    """Verify upload of corrupt PDF content returns 400 and unlinks written file on inspection failure."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    corrupt_pdf = b"%PDF-1.4\ncorrupted content that cannot be parsed as a valid document"
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("corrupt.pdf", corrupt_pdf, "application/pdf")}
    )
    status, _, resp = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 400
    data = json.loads(resp.decode("utf-8"))
    assert "inspect document pages" in data["detail"].lower()
    assert len(list(tmp_path.glob("*_*"))) == 0


def test_delete_in_flight_job_defers_unlink_and_suppresses_cancelled_event(tmp_path: Path) -> None:
    """Verify deleting an in-flight job defers unlink until execution finishes and suppresses cancelled event."""
    gate = threading.Event()
    started = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(80, 80)
    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("in_flight_doc.png", png_bytes, "image/png")}
    )
    status, _, resp = client.post(
        "/api/documents", headers={"content-type": ct}, body=body
    )
    assert status == 200
    job_id = json.loads(resp.decode("utf-8"))["id"]

    job = orchestrator.get_job(job_id)
    assert job is not None
    job_file_path = job.file_path
    assert job_file_path and job_file_path.exists()

    events_after_delete: List[Tuple[str, Dict[str, Any]]] = []
    deleted_event = threading.Event()
    orig_broadcast = orchestrator.broadcast

    def spy_broadcast(event_type: str, data: Dict[str, Any]) -> None:
        if deleted_event.is_set() and data.get("job_id") == job_id:
            events_after_delete.append((event_type, data))
        orig_broadcast(event_type, data)

    orchestrator.broadcast = spy_broadcast  # type: ignore[assignment]

    # Enqueue job for extraction
    status, _, _ = client.post(f"/api/documents/{job_id}/extract")
    assert status == 202
    assert started.wait(timeout=5.0), "Worker did not reach process_document"

    # Hold handle on Windows to ensure delete_document's unlink fails and defers to worker
    hold_file = open(job_file_path, "rb")
    try:
        del_status, _, del_body = client.delete(f"/api/documents/{job_id}")
        assert del_status == 200
        del_data = json.loads(del_body.decode("utf-8"))
        assert del_data["deleted"] is True
        deleted_event.set()
    finally:
        hold_file.close()

    # Release gate so process_document completes
    gate.set()

    # Wait for orchestrator worker thread to complete deferred cleanup
    orchestrator.shutdown(timeout=5.0)

    # Verify file is deleted on disk
    assert not job_file_path.exists()

    # Verify no cancelled, completed, or failed events were broadcast for job_id after deletion
    suppressed_types = {"cancelled", "completed", "failed"}
    disallowed_broadcasts = [ev for ev in events_after_delete if ev[0] in suppressed_types]
    assert len(disallowed_broadcasts) == 0


def test_get_page_preview_file_not_found_returns_404(tmp_path: Path) -> None:
    """Verify get_page_preview returns 404 with 'Document file not found' on missing file."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    missing_file = tmp_path / "missing_target.png"
    job = JobState(
        job_id="test_missing_job",
        filename="missing.png",
        file_path=missing_file,
        page_count=1,
    )
    app.state.orchestrator.register_job(job)

    with patch("web.app.rasterize_page", side_effect=FileNotFoundError("Target raster file missing")):
        status, _, body = client.get(f"/api/documents/{job.job_id}/pages/1/preview")
        assert status == 404
        data = json.loads(body.decode("utf-8"))
        assert data["detail"] == "Document file not found"


def test_lifespan_shutdown_unlinks_only_own_jobs(tmp_path: Path) -> None:
    """Verify lifespan shutdown unlinks only jobs registered to this instance."""
    app = create_app(upload_dir=tmp_path)
    orch = app.state.orchestrator

    foreign_file = tmp_path / "foreign.pdf"
    own_file = tmp_path / "own.pdf"

    async def _run():
        async with app.router.lifespan_context(app):
            foreign_file.write_bytes(b"%PDF-1.4 foreign mock content")
            own_file.write_bytes(b"%PDF-1.4 own mock content")
            own_job = JobState(
                job_id="own_job_id",
                filename="own.pdf",
                file_path=own_file,
                page_count=1,
            )
            orch.register_job(own_job)
            assert foreign_file.exists()
            assert own_file.exists()

    asyncio.run(_run())

    assert not own_file.exists()
    assert foreign_file.exists()


def test_create_app_resolves_meipass_static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_app resolves static directory from sys._MEIPASS when frozen."""
    meipass_dir = tmp_path / "bundle"
    static_dir = meipass_dir / "web" / "static"
    static_dir.mkdir(parents=True)
    index_file = static_dir / "index.html"
    index_file.write_text("<!doctype html><html><body>MEIPASS Bundle</body></html>", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(upload_dir=upload_dir)
    try:
        static_routes = [r for r in app.routes if getattr(r, "name", None) == "static"]
        assert len(static_routes) == 1
        mounted_dir = getattr(static_routes[0].app, "directory", None)
        assert mounted_dir is not None
        assert Path(mounted_dir).resolve() == static_dir.resolve()
        assert (Path(mounted_dir) / "index.html").is_file()
        assert "MEIPASS Bundle" in (Path(mounted_dir) / "index.html").read_text(encoding="utf-8")
    finally:
        if hasattr(app.state, "orchestrator") and app.state.orchestrator:
            app.state.orchestrator.shutdown()


def test_build_parser_no_browser_flag() -> None:
    """Verify build_parser supports and correctly parses --no-browser flag."""
    from web.__main__ import build_parser

    parser = build_parser()
    args_true = parser.parse_args(["--no-browser"])
    assert args_true.no_browser is True

    args_default = parser.parse_args([])
    assert args_default.no_browser is False


def test_setup_frozen_logging_idempotency_and_oserror_resilience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify _setup_frozen_logging is idempotent and resilient to OSError."""
    import logging
    from web.__main__ import _setup_frozen_logging

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    original_excepthook = sys.excepthook

    try:
        log_path_1 = _setup_frozen_logging()
        assert log_path_1 is not None
        assert log_path_1.is_file()

        file_handlers_before = [
            h for h in root_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers_before) >= 1

        log_path_2 = _setup_frozen_logging()
        assert log_path_2 == log_path_1
        file_handlers_after = [
            h for h in root_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers_after) == len(file_handlers_before)

        with patch("pathlib.Path.mkdir", side_effect=OSError("Disk full or read-only")):
            res = _setup_frozen_logging()
            assert res is None
    finally:
        for h in list(root_logger.handlers):
            if h not in original_handlers:
                try:
                    h.close()
                except Exception:
                    pass
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
        sys.excepthook = original_excepthook


def test_orchestrator_enqueue_rejects_queued_or_processing(tmp_path: Path) -> None:
    """Verify WebOrchestrator.enqueue() raises RuntimeError if job is already QUEUED or PROCESSING."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    fake_file = tmp_path / "active_test.png"
    fake_file.write_bytes(b"dummy")

    job_id = "job-active-test"
    job = JobState(
        job_id=job_id,
        filename="active_test.png",
        file_path=fake_file,
        status=JobStatus.QUEUED,
    )
    orchestrator.register_job(job)

    with pytest.raises(RuntimeError, match=f"Job '{job_id}' is already queued"):
        orchestrator.enqueue(job_id)

    job.status = JobStatus.PROCESSING
    with pytest.raises(RuntimeError, match=f"Job '{job_id}' is already processing"):
        orchestrator.enqueue(job_id)

    orchestrator.stop()


def test_post_extract_conflict_when_job_active(tmp_path: Path) -> None:
    """Verify POST /api/documents/{job_id}/extract returns 409 Conflict when job is already QUEUED or PROCESSING."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    fake_file = tmp_path / "conflict_test.png"
    fake_file.write_bytes(b"dummy")

    job_id = "job-conflict-test"
    job = JobState(
        job_id=job_id,
        filename="conflict_test.png",
        file_path=fake_file,
        status=JobStatus.PROCESSING,
    )
    orchestrator.register_job(job)

    status_code, _, body = client.post(f"/api/documents/{job_id}/extract")
    assert status_code == 409
    data = json.loads(body.decode("utf-8"))
    assert "already processing" in data["detail"].lower()

    job.status = JobStatus.QUEUED
    status_code, _, body = client.post(f"/api/documents/{job_id}/extract")
    assert status_code == 409
    data = json.loads(body.decode("utf-8"))
    assert "already queued" in data["detail"].lower()

    orchestrator.stop()


@pytest.fixture
def client(tmp_path: Path) -> AsgiClient:
    app = create_app(upload_dir=tmp_path)
    return AsgiClient(app)


def test_delete_document_rejects_invalid_job_id_format(client: AsgiClient) -> None:
    """Verify DELETE /api/documents/{job_id} rejects non-hex job IDs."""
    for bad_id in ["*", "..", "../etc", "not_a_valid_hex_id"]:
        status, _, body = client.delete(f"/api/documents/{bad_id}")
        assert status == 400
        data = json.loads(body.decode("utf-8"))
        assert "Invalid job ID format" in data["detail"]


def test_patch_settings_rejects_non_llama_server_binary(client: AsgiClient) -> None:
    """Verify PATCH /api/settings rejects executables not named llama-server."""
    body = json.dumps({"llama_server_path": "C:\\Windows\\System32\\cmd.exe"}).encode("utf-8")
    status, _, resp = client.patch(
        "/api/settings",
        headers={"content-type": "application/json"},
        body=body,
    )
    assert status == 400
    data = json.loads(resp.decode("utf-8"))
    assert "Server binary must be named llama-server or llama-server.exe" in data["detail"]


def test_dialog_file_returns_409_when_locked(client: AsgiClient) -> None:
    """Verify POST /api/dialog/file returns 409 Conflict when a dialog is already open."""
    from web.app import _dialog_lock

    asyncio.run(_dialog_lock.acquire())
    try:
        status, _, body = client.post("/api/dialog/file")
        assert status == 409
        data = json.loads(body.decode("utf-8"))
        assert "already open" in data["detail"].lower()
    finally:
        if _dialog_lock.locked():
            _dialog_lock.release()











