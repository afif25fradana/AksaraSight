"""Unit and integration tests for AksaraSight Web API."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import time
from typing import Any, Dict, Optional, Tuple
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest

from core.models import JobStatus as CoreJobStatus, OCRResult, PageResult
from web.app import app, orchestrator
from web.orchestrator import JobStatus, WebOrchestrator
from web.security import (
    generate_secure_upload_path,
    validate_loopback_host,
)


class AsgiResponse:
    """Represents an HTTP response from direct in-memory ASGI invocation."""

    def __init__(self, status_code: int, headers: Dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


class AsgiTestClient:
    """Lightweight in-memory test client directly invoking the ASGI application.

    Zero external HTTP client dependencies (avoids httpx version churn).
    """

    def __init__(self, asgi_app: Any, default_host: str = "127.0.0.1:8000") -> None:
        self.asgi_app = asgi_app
        self.default_host = default_host

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        query_string: str = "",
    ) -> AsgiResponse:
        hdrs: Dict[str, str] = {"host": self.default_host}
        if headers:
            for k, v in headers.items():
                hdrs[k.lower()] = v

        raw_headers = [
            (k.encode("latin-1"), v.encode("latin-1"))
            for k, v in hdrs.items()
        ]

        if "?" in path and not query_string:
            path, query_string = path.split("?", 1)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": query_string.encode("ascii"),
            "headers": raw_headers,
            "client": ("127.0.0.1", 52345),
            "server": ("127.0.0.1", 8000),
        }

        response_start: Dict[str, Any] = {}
        response_body: list[bytes] = []

        async def receive() -> Dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_start.update(message)
            elif message["type"] == "http.response.body":
                response_body.append(message.get("body", b""))

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self.asgi_app(scope, receive, send))
        finally:
            loop.close()

        status_code = response_start.get("status", 500)
        resp_headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in response_start.get("headers", [])
        }
        return AsgiResponse(status_code, resp_headers, b"".join(response_body))

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        query_string: str = "",
    ) -> AsgiResponse:
        return self.request("GET", path, headers=headers, query_string=query_string)

    def post(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        files: Optional[Dict[str, Tuple[str, bytes, str]]] = None,
    ) -> AsgiResponse:
        req_headers = dict(headers or {})
        payload = body

        if files:
            boundary = "----WebKitFormBoundaryAksaraSightSpike789"
            req_headers["content-type"] = f"multipart/form-data; boundary={boundary}"
            chunks = []
            for field_name, (fname, fbytes, ctype) in files.items():
                chunks.append(
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{fname}"\r\n'
                    f"Content-Type: {ctype}\r\n\r\n".encode("utf-8")
                )
                chunks.append(fbytes)
                chunks.append(b"\r\n")
            chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
            payload = b"".join(chunks)
            req_headers["content-length"] = str(len(payload))

        return self.request("POST", path, headers=req_headers, body=payload)


@pytest.fixture
def client() -> AsgiTestClient:
    """Create an AsgiTestClient bound to the FastAPI application."""
    orchestrator.start()
    return AsgiTestClient(app)


@pytest.fixture
def sample_png_bytes() -> bytes:
    """Generate a valid 20x20 in-memory PNG image."""
    img = Image.new("RGB", (20, 20), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# -------------------------------------------------------------------------
# Security Guard Tests
# -------------------------------------------------------------------------

def test_host_header_rejection_dns_rebinding(client: AsgiTestClient) -> None:
    """Host headers not in loopback set must be rejected with 400 Bad Request."""
    # Evil external host
    res = client.get("/health", headers={"Host": "evil-domain.com"})
    assert res.status_code == 400
    assert "Invalid Host header" in res.text

    # Another malicious external host
    res2 = client.get("/health", headers={"Host": "attacker.local:8000"})
    assert res2.status_code == 400
    assert "Invalid Host header" in res2.text

    # Loopback IP and localhost must be accepted
    res_ok1 = client.get("/health", headers={"Host": "127.0.0.1:8000"})
    assert res_ok1.status_code == 200

    res_ok2 = client.get("/health", headers={"Host": "localhost:8000"})
    assert res_ok2.status_code == 200

    res_ok3 = client.get("/health", headers={"Host": "testserver"})
    assert res_ok3.status_code == 200


def test_origin_header_rejection_csrf(client: AsgiTestClient) -> None:
    """Non-loopback Origin header on state-changing methods must be rejected with 403 Forbidden."""
    # Attacker website attempting CSRF POST
    res = client.post(
        "/api/documents",
        headers={"Origin": "https://evil-hacker.com"},
        files={"file": ("test.png", b"fake", "image/png")},
    )
    assert res.status_code == 403
    assert "Cross-origin request rejected" in res.text

    # Malicious subdomain CSRF
    res2 = client.post(
        "/api/documents/nonexistent/extract",
        headers={"Origin": "http://attacker.com:3000"},
    )
    assert res2.status_code == 403
    assert "Cross-origin request rejected" in res2.text

    # Loopback origins must pass through origin check
    res_ok = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"Origin": "http://localhost:3000"},
    )
    # Origin passes; returns 404 because job doesn't exist
    assert res_ok.status_code == 404


def test_validate_loopback_host() -> None:
    """Server entrypoint must strictly reject binding to non-loopback interfaces."""
    with pytest.raises(ValueError, match="Server host must be loopback"):
        validate_loopback_host("0.0.0.0")

    with pytest.raises(ValueError, match="Server host must be loopback"):
        validate_loopback_host("192.168.1.50")

    with pytest.raises(ValueError, match="Server host must be loopback"):
        validate_loopback_host("example.com")

    # Valid loopback addresses
    validate_loopback_host("127.0.0.1")
    validate_loopback_host("localhost")
    validate_loopback_host("::1")


def test_upload_path_traversal_prevention(tmp_path: Path) -> None:
    """Filenames with directory traversal patterns must be safely constrained inside target directory."""
    # Attempt to traverse up out of upload directory
    traversal_filename = "../../../secret_system_file.png"
    secure_path = generate_secure_upload_path(traversal_filename, base_dir=tmp_path)
    assert secure_path.is_relative_to(tmp_path)
    assert secure_path.parent == tmp_path

    # Unsupported extension
    with pytest.raises(ValueError, match="Unsupported file extension"):
        generate_secure_upload_path("exploit.exe", base_dir=tmp_path)


def test_upload_size_limit_and_empty_file(client: AsgiTestClient) -> None:
    """Empty files and uploads exceeding 100 MB must be rejected."""
    # Empty file
    res_empty = client.post(
        "/api/documents",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert res_empty.status_code == 400
    assert "Empty file" in res_empty.text

    # Unsupported file extension
    res_bad_ext = client.post(
        "/api/documents",
        files={"file": ("script.py", b"print('hi')", "text/plain")},
    )
    assert res_bad_ext.status_code == 400
    assert "Unsupported file extension" in res_bad_ext.text

    # Exceeding size cap
    with patch("web.app.MAX_UPLOAD_SIZE", 100):
        oversized_data = b"x" * 150
        res_oversized = client.post(
            "/api/documents",
            files={"file": ("big.png", oversized_data, "image/png")},
        )
        assert res_oversized.status_code == 413


# -------------------------------------------------------------------------
# Document Workflow & Queue Lifecycle Tests
# -------------------------------------------------------------------------

def test_document_upload_and_preview(client: AsgiTestClient, sample_png_bytes: bytes) -> None:
    """Uploading a valid image document probes page count and enables preview rendering."""
    res = client.post(
        "/api/documents",
        files={"file": ("receipt.png", sample_png_bytes, "image/png")},
    )
    assert res.status_code == 201
    data = res.json()
    assert "job_id" in data
    assert data["filename"] == "receipt.png"
    assert data["total_pages"] == 1
    assert data["status"] == "QUEUED"

    job_id = data["job_id"]

    # Request valid preview for page 1
    prev_res = client.get(f"/api/documents/{job_id}/pages/1/preview")
    assert prev_res.status_code == 200
    assert prev_res.headers["content-type"] == "image/png"
    assert len(prev_res.content) > 0

    # Request invalid page number
    bad_page_res = client.get(f"/api/documents/{job_id}/pages/2/preview")
    assert bad_page_res.status_code == 400


def test_document_extraction_and_export_flow(client: AsgiTestClient, sample_png_bytes: bytes) -> None:
    """Full end-to-end integration: upload -> extract -> progress -> export (DOCX, MD, JSON)."""
    # 1. Upload document
    upload_res = client.post(
        "/api/documents",
        files={"file": ("invoice.png", sample_png_bytes, "image/png")},
    )
    assert upload_res.status_code == 201
    job_id = upload_res.json()["job_id"]

    # 2. Mock engine to produce deterministic OCRResult
    mock_engine = MagicMock()

    def fake_process(source, cancel_token=None, progress_callback=None):
        page = PageResult(
            page_num=1,
            markdown="# INVOICE\n\nTotal: IDR 50.000",
            latency=0.45,
            raw_json={"usage": {"total_tokens": 120}},
            status=CoreJobStatus.SUCCESS,
        )
        if progress_callback:
            progress_callback(1, 1, page)
        return OCRResult(
            file_path=str(source),
            pages=[page],
            status=CoreJobStatus.SUCCESS,
            total_duration=0.5,
        )

    mock_engine.process_document.side_effect = fake_process

    # Point orchestrator to mock engine
    original_engine = orchestrator.engine
    orchestrator.engine = mock_engine
    try:
        # 3. Enqueue extraction
        extract_res = client.post(f"/api/documents/{job_id}/extract")
        assert extract_res.status_code == 202

        # 4. Wait briefly for background worker to complete
        start = time.time()
        while time.time() - start < 3.0:
            job = orchestrator.jobs.get(job_id)
            if job and job.status == JobStatus.SUCCESS:
                break
            time.sleep(0.05)

        job = orchestrator.jobs[job_id]
        assert job.status == JobStatus.SUCCESS
        assert 1 in job.pages_data
        assert "INVOICE" in job.pages_data[1]["text"]

        # 5. Export to DOCX
        docx_res = client.get(f"/api/documents/{job_id}/export?format=docx")
        assert docx_res.status_code == 200
        assert "application/vnd.openxmlformats" in docx_res.headers["content-type"]
        assert 'attachment; filename="invoice.docx"' in docx_res.headers["content-disposition"]
        assert len(docx_res.content) > 500  # valid binary docx payload

        # 6. Export to Markdown
        md_res = client.get(f"/api/documents/{job_id}/export?format=md")
        assert md_res.status_code == 200
        assert "text/markdown" in md_res.headers["content-type"]
        assert "# INVOICE" in md_res.text

        # 7. Export to JSON
        json_res = client.get(f"/api/documents/{job_id}/export?format=json")
        assert json_res.status_code == 200
        assert "application/json" in json_res.headers["content-type"]
        json_data = json_res.json()
        assert json_data["status"] == "SUCCESS"
    finally:
        orchestrator.engine = original_engine


def test_cancellation_flow(client: AsgiTestClient, sample_png_bytes: bytes) -> None:
    """Cancelling a queued job transitions status to CANCELLED cleanly."""
    upload_res = client.post(
        "/api/documents",
        files={"file": ("doc_to_cancel.png", sample_png_bytes, "image/png")},
    )
    job_id = upload_res.json()["job_id"]

    # Cancel while still queued
    cancel_res = client.post(f"/api/documents/{job_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    job = orchestrator.jobs[job_id]
    assert job.status == JobStatus.CANCELLED
    assert job.cancel_event.is_set()


def test_orchestrator_event_subscription() -> None:
    """Orchestrator pub/sub properly broadcasts events to subscriber queues."""
    orch = WebOrchestrator()
    loop = asyncio.new_event_loop()
    try:
        q = orch.subscribe(loop)
        orch.publish_event("test_event", {"foo": "bar"})

        # Run loop briefly to process threadsafe call
        loop.stop()
        loop.run_forever()

        assert not q.empty()
        item = q.get_nowait()
        assert item["event"] == "test_event"
        assert item["data"] == {"foo": "bar"}

        orch.unsubscribe((loop, q))
    finally:
        loop.close()
