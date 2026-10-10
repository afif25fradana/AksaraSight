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

from core.client import ServerOfflineError
from core.models import JobConfig, JobStatus as CoreJobStatus, OCRResult, PageResult
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


def _create_sample_png_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MockEngine:
    """Mock OCR engine for controlled end-to-end web testing."""

    def __init__(self, failure_mode: Optional[str] = None) -> None:
        self.failure_mode = failure_mode
        self.last_cancel_token: Optional[threading.Event] = None
        self.process_delay: float = 0.0

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
    mock_eng = MockEngine()
    mock_eng.process_delay = 0.2  # Simulate delay to allow cancel signal
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

    # Start extract then immediately cancel
    client.post(f"/api/documents/{job_id}/extract")
    status, _, _ = client.post(f"/api/documents/{job_id}/cancel")
    assert status == 200

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


def test_lifespan_cleans_up_upload_scratch(tmp_path: Path) -> None:
    """Verify FastAPI lifespan shutdown cleans up all files in upload directory."""
    app = create_app(upload_dir=tmp_path)

    # Populate upload directory with session files
    file1 = tmp_path / "session_file1.png"
    file2 = tmp_path / "session_file2.pdf"
    file1.write_bytes(b"data1")
    file2.write_bytes(b"data2")
    assert file1.exists()
    assert file2.exists()

    async def _run_lifespan():
        async with app.router.lifespan_context(app):
            # During startup/running, files remain
            assert file1.exists()
            assert file2.exists()

    asyncio.run(_run_lifespan())

    # On shutdown, all files in upload directory must be deleted
    assert not file1.exists()
    assert not file2.exists()
    assert len(list(tmp_path.iterdir())) == 0
