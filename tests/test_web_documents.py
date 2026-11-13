"""Tests for Web document upload, extraction, cancellations, and queue lifecycle."""

import asyncio
import io
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch
import urllib3

from PIL import Image
import pypdfium2 as pdfium
import pytest

from config.settings import Settings
from core.client import ClientError
from core.engine import OCREngine
from core.models import JobStatus as CoreJobStatus
from web.app import create_app
from web.orchestrator import JobState, JobStatus, WebOrchestrator
from core.pipeline import OversizedImageError
from tests.test_pipeline import MINIMAL_ENCRYPTED_PDF
from tests.web_fixtures import (
    AsgiClient,
    MockEngine,
    _create_sample_png_bytes,
)


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


def test_extract_endpoint_custom_dpi_and_prompt_mode(tmp_path: Path) -> None:
    """Verify POST /api/documents/{id}/extract accepts prompt_mode and dpi, passing them to JobConfig."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("custom_dpi.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    # Call extract with prompt_mode='table' and dpi=150
    payload = json.dumps({"prompt_mode": "table", "dpi": 150}).encode("utf-8")
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
    assert job.dpi == 150

    for _ in range(50):
        job = orchestrator.get_job(doc_id)
        if job and job.status == JobStatus.SUCCESS:
            break
        time.sleep(0.05)

    assert job is not None
    assert job.status == JobStatus.SUCCESS
    assert mock_eng.last_config is not None
    assert mock_eng.last_config.prompt_mode == "table"
    assert mock_eng.last_config.dpi == 150

    orchestrator.stop()


def test_extract_endpoint_invalid_dpi(tmp_path: Path) -> None:
    """Verify POST /api/documents/{id}/extract validates dpi between 50 and 600."""
    mock_eng = MockEngine()
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    png_bytes = _create_sample_png_bytes(50, 50)
    body, ct = urllib3.encode_multipart_formdata({"file": ("invalid_dpi.png", png_bytes, "image/png")})
    status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
    assert status == 200
    doc_id = json.loads(resp.decode("utf-8"))["id"]

    for invalid_dpi in [49, 601, -10]:
        payload = json.dumps({"dpi": invalid_dpi}).encode("utf-8")
        status, _, err_resp = client.post(
            f"/api/documents/{doc_id}/extract",
            headers={"content-type": "application/json"},
            body=payload,
        )
        assert status == 400
        data = json.loads(err_resp.decode("utf-8"))
        assert "Invalid dpi" in data["detail"]

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

    # Calling rasterize_page without mock on non-existent file raises FilePreflightError;
    # verify web layer translates it to 404 rather than 500
    status, _, body = client.get(f"/api/documents/{job.job_id}/pages/1/preview")
    assert status == 404
    data = json.loads(body.decode("utf-8"))
    assert data["detail"] == "Document file not found"


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


def test_delete_document_rejects_invalid_job_id_format(client: AsgiClient) -> None:
    """Verify DELETE /api/documents/{job_id} rejects non-hex job IDs."""
    for bad_id in ["*", "..", "../etc", "not_a_valid_hex_id"]:
        status, _, body = client.delete(f"/api/documents/{bad_id}")
        assert status == 400
        data = json.loads(body.decode("utf-8"))
        assert "Invalid job ID format" in data["detail"]


def test_upload_encrypted_pdf_rejection(tmp_path: Path) -> None:
    """Verify upload of encrypted PDF returns 400 with diagnostic message and unlinks upload."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    body, ct = urllib3.encode_multipart_formdata(
        {"file": ("secret.pdf", MINIMAL_ENCRYPTED_PDF, "application/pdf")}
    )
    status, _, resp = client.post(
        "/api/documents",
        headers={"content-type": ct},
        body=body,
    )
    assert status == 400
    data = json.loads(resp.decode("utf-8"))
    assert data["detail"] == "Document is password-protected or encrypted"
    assert list(tmp_path.glob("*secret.pdf")) == []


def test_orchestrator_job_eviction_prunes_terminal_jobs(tmp_path: Path) -> None:
    """Verify that when jobs exceed max_stored_jobs, oldest terminal jobs are pruned."""
    mock_engine = MockEngine()
    orch = WebOrchestrator(engine=mock_engine, max_stored_jobs=3)  # type: ignore[arg-type]
    try:
        f1 = tmp_path / "doc1.pdf"
        f1.write_bytes(b"dummy1")
        f2 = tmp_path / "doc2.pdf"
        f2.write_bytes(b"dummy2")
        f3 = tmp_path / "doc3.pdf"
        f3.write_bytes(b"dummy3")
        f4 = tmp_path / "doc4.pdf"
        f4.write_bytes(b"dummy4")

        j1 = JobState(job_id="j1", filename="doc1.pdf", file_path=f1, status=JobStatus.SUCCESS)
        j2 = JobState(job_id="j2", filename="doc2.pdf", file_path=f2, status=JobStatus.FAILED)
        j3 = JobState(job_id="j3", filename="doc3.pdf", file_path=f3, status=JobStatus.UPLOADED)

        orch.register_job(j1)
        orch.register_job(j2)
        orch.register_job(j3)
        assert len(orch.jobs) == 3

        j4 = JobState(job_id="j4", filename="doc4.pdf", file_path=f4, status=JobStatus.UPLOADED)
        orch.register_job(j4)

        assert len(orch.jobs) == 3
        assert "j1" not in orch.jobs
        assert "j2" in orch.jobs
        assert "j3" in orch.jobs
        assert "j4" in orch.jobs
        assert not f1.exists()
    finally:
        orch.stop()


def test_sse_events_keepalive_ping(tmp_path: Path) -> None:
    """Verify /api/events emits keepalive ping when queue is idle."""
    mock_engine = MockEngine()
    orch = WebOrchestrator(engine=mock_engine)  # type: ignore[arg-type]
    app = create_app(engine=mock_engine, orchestrator=orch, upload_dir=tmp_path)  # type: ignore[arg-type]

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

    ping_received = asyncio.Event()

    async def receive() -> Dict[str, Any]:
        await ping_received.wait()
        return {"type": "http.disconnect"}

    async def send(message: Dict[str, Any]) -> None:
        if message["type"] == "http.response.body":
            body = message.get("body", b"")
            if b": ping" in body:
                ping_received.set()

    async def _run() -> None:
        original_subscribe = orch.subscribe

        def _fast_subscribe():
            return original_subscribe(timeout=0.05)

        orch.subscribe = _fast_subscribe  # type: ignore[method-assign]
        app_task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(ping_received.wait(), timeout=2.0)
        finally:
            orch.stop()
            app_task.cancel()
            try:
                await app_task
            except (asyncio.CancelledError, Exception):
                pass

    asyncio.run(_run())


def test_get_page_preview_oversized_image_returns_422(tmp_path: Path) -> None:
    """Verify get_page_preview returns 422 with sanitized error on OversizedImageError."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    file_path = tmp_path / "huge.png"
    job = JobState(
        job_id="test_huge_preview_job",
        filename="huge.png",
        file_path=file_path,
        page_count=1,
    )
    app.state.orchestrator.register_job(job)

    with patch("web.app.rasterize_page", side_effect=OversizedImageError(f"Image dimensions exceed threshold: {file_path}")):
        status, _, body = client.get(f"/api/documents/{job.job_id}/pages/1/preview")
        assert status == 422
        data = json.loads(body.decode("utf-8"))
        assert "Page dimensions exceed preview limit" in data["detail"]
        assert str(file_path) not in data["detail"]


def test_cancel_queued_then_reextract_no_duplicate_execution(tmp_path: Path) -> None:
    """Verify that cancelling a QUEUED job and immediately re-extracting executes exactly once."""
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        # Upload doc 1 (blocking job that holds worker at gate)
        png_bytes = _create_sample_png_bytes(50, 50)
        body, ct = urllib3.encode_multipart_formdata({"file": ("doc1.png", png_bytes, "image/png")})
        status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
        assert status == 200
        doc1_id = json.loads(resp.decode("utf-8"))["id"]

        # Upload doc 2 (target job to be queued, cancelled, and re-extracted)
        body, ct = urllib3.encode_multipart_formdata({"file": ("doc2.png", png_bytes, "image/png")})
        status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
        assert status == 200
        doc2_id = json.loads(resp.decode("utf-8"))["id"]

        # Enqueue doc 1 -> enters PROCESSING and holds at gate
        status, _, _ = client.post(f"/api/documents/{doc1_id}/extract")
        assert status == 202

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j1 = orchestrator.get_job(doc1_id)
            if j1 and j1.status == JobStatus.PROCESSING:
                break
            time.sleep(0.02)
        assert orchestrator.get_job(doc1_id).status == JobStatus.PROCESSING

        # Enqueue doc 2 -> queued behind doc 1
        status, _, _ = client.post(f"/api/documents/{doc2_id}/extract")
        assert status == 202
        assert orchestrator.get_job(doc2_id).status == JobStatus.QUEUED

        # Cancel doc 2 while QUEUED in queue
        status, _, _ = client.post(f"/api/documents/{doc2_id}/cancel")
        assert status == 200
        assert orchestrator.get_job(doc2_id).status == JobStatus.CANCELLED

        # Immediately re-extract doc 2
        status, _, _ = client.post(f"/api/documents/{doc2_id}/extract")
        assert status == 202

        # Release gate for doc 1 to finish, allowing worker to process doc 2's queue entries
        gate.set()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            j2 = orchestrator.get_job(doc2_id)
            if j2 and j2.status == JobStatus.SUCCESS:
                break
            time.sleep(0.05)

        assert orchestrator.get_job(doc2_id).status == JobStatus.SUCCESS
        # Total executions: doc 1 (1) + doc 2 (1) = 2.
        # In bug condition, doc 2 ran twice (total = 3).
        # In fixed condition, doc 2 ran exactly once (total = 2).
        assert len(mock_eng.executed_configs) == 2
    finally:
        gate.set()
        orchestrator.stop()


def test_cancel_processing_then_reextract_permits_enqueue(tmp_path: Path) -> None:
    """Verify that cancelling an active PROCESSING job allows immediate re-extraction without 409 Conflict."""
    gate = threading.Event()
    mock_eng = MockEngine(process_gate=gate)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        # Upload doc
        png_bytes = _create_sample_png_bytes(50, 50)
        body, ct = urllib3.encode_multipart_formdata({"file": ("doc.png", png_bytes, "image/png")})
        status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
        assert status == 200
        doc_id = json.loads(resp.decode("utf-8"))["id"]

        # Enqueue doc
        status, _, _ = client.post(f"/api/documents/{doc_id}/extract")
        assert status == 202

        # Wait until job enters PROCESSING and pauses at gate
        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job(doc_id)
            if j and j.status == JobStatus.PROCESSING:
                break
            time.sleep(0.02)
        assert orchestrator.get_job(doc_id).status == JobStatus.PROCESSING

        # Cancel document
        status, _, _ = client.post(f"/api/documents/{doc_id}/cancel")
        assert status == 200

        # Immediately call extract without manually cheating status = CANCELLED
        status, _, body = client.post(f"/api/documents/{doc_id}/extract")
        # In bug condition, status is 409 Conflict ("Job is already processing")
        # In fixed condition, status must be 202 Accepted
        assert status == 202
    finally:
        gate.set()
        orchestrator.stop()


def test_cancel_processing_then_immediate_reextract_isolates_run_cancel_tokens(tmp_path: Path) -> None:
    """Verify that when an active job is cancelled and immediately re-enqueued, Run 1 receives Run 1's set cancel_token."""
    gate = threading.Event()
    started = threading.Event()
    mock_eng = MockEngine(process_gate=gate, processing_started=started)
    orchestrator = WebOrchestrator(engine=mock_eng)
    app = create_app(engine=mock_eng, orchestrator=orchestrator, upload_dir=tmp_path)
    client = AsgiClient(app)

    try:
        # Upload doc
        png_bytes = _create_sample_png_bytes(50, 50)
        body, ct = urllib3.encode_multipart_formdata({"file": ("isolate_test.png", png_bytes, "image/png")})
        status, _, resp = client.post("/api/documents", headers={"content-type": ct}, body=body)
        assert status == 200
        doc_id = json.loads(resp.decode("utf-8"))["id"]

        # Enqueue Run 1 with dpi=100 and prompt_mode="text"
        status, _, _ = client.post(
            f"/api/documents/{doc_id}/extract",
            headers={"content-type": "application/json"},
            body=json.dumps({"dpi": 100, "prompt_mode": "text"}).encode("utf-8"),
        )
        assert status == 202

        # Wait until Run 1 starts processing and pauses at gate
        assert started.wait(timeout=5.0)

        # Cancel Run 1 while processing
        status, _, _ = client.post(f"/api/documents/{doc_id}/cancel")
        assert status == 200

        # Immediately re-extract as Run 2 with dpi=150 and prompt_mode="table"
        status, _, _ = client.post(
            f"/api/documents/{doc_id}/extract",
            headers={"content-type": "application/json"},
            body=json.dumps({"dpi": 150, "prompt_mode": "table"}).encode("utf-8"),
        )
        assert status == 202

        # Release gate so Run 1 finishes and worker can process Run 2
        gate.set()

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job(doc_id)
            if j and j.status == JobStatus.SUCCESS and len(mock_eng.executed_cancel_tokens) >= 2:
                break
            time.sleep(0.05)

        # Verify two executions occurred
        assert len(mock_eng.executed_cancel_tokens) == 2
        run1_token = mock_eng.executed_cancel_tokens[0]
        run2_token = mock_eng.executed_cancel_tokens[1]

        # Run 1 received Run 1's cancel token, which was set upon cancellation
        assert run1_token is not None
        assert run1_token.is_set() is True

        # Run 2 received a separate, fresh cancel token that was never cancelled
        assert run2_token is not None
        assert run2_token is not run1_token

        # Verify parameter snapshot isolation
        assert len(mock_eng.executed_configs) == 2
        assert mock_eng.executed_configs[0].dpi == 100
        assert mock_eng.executed_configs[0].prompt_mode == "text"
        assert mock_eng.executed_configs[1].dpi == 150
        assert mock_eng.executed_configs[1].prompt_mode == "table"
    finally:
        gate.set()
        orchestrator.stop()


def test_job_status_partial_enum_and_snapshot_mapping() -> None:
    """Verify JobStatus.PARTIAL enum value and its representation in get_jobs_snapshot()."""
    assert hasattr(JobStatus, "PARTIAL")
    assert JobStatus.PARTIAL == "PARTIAL"

    orchestrator = WebOrchestrator(engine=MockEngine())
    job = JobState(
        job_id="test-partial-snapshot",
        filename="doc.pdf",
        file_path=Path("doc.pdf"),
        status=JobStatus.PARTIAL,
        page_count=2,
        pages_data={
            1: {"pageNumber": 1, "text": "Page 1 truncated", "truncated": True},
            2: {"pageNumber": 2, "text": "Page 2 full", "truncated": False},
        },
        error="Output truncated on page(s) 1 (hit token limit)",
    )
    orchestrator.register_job(job)
    snapshot = orchestrator.get_jobs_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0]["status"] == "Truncated"
    assert snapshot[0]["statusNote"] == "Output truncated on page(s) 1 (hit token limit)"
    assert snapshot[0]["pagesData"][1]["isTruncated"] is True
    assert snapshot[0]["pagesData"][2]["isTruncated"] is False


def test_orchestrator_worker_loop_partial_truncation_lifecycle(tmp_path: Path) -> None:
    """Verify worker loop handles truncated results, setting JobStatus.PARTIAL and broadcasting details."""
    from core.models import OCRResult, PageResult

    class TruncatedEngine:
        def process_document(
            self,
            source: Any,
            config: Optional[Any] = None,
            cancel_token: Optional[threading.Event] = None,
            progress_callback: Optional[Any] = None,
        ) -> OCRResult:
            page1 = PageResult(
                page_num=1,
                markdown="Truncated text...",
                truncated=True,
                status=CoreJobStatus.PARTIAL,
            )
            page2 = PageResult(
                page_num=2,
                markdown="Complete text",
                truncated=False,
                status=CoreJobStatus.SUCCESS,
            )
            if progress_callback:
                progress_callback(1, 2, page1)
                progress_callback(2, 2, page2)
            res = OCRResult(file_path=str(source), pages=[page1, page2])
            res.status = CoreJobStatus.PARTIAL
            return res

    sample_png = tmp_path / "sample_trunc.png"
    sample_png.write_bytes(_create_sample_png_bytes())

    orchestrator = WebOrchestrator(engine=TruncatedEngine())
    events: List[Tuple[str, Dict[str, Any]]] = []
    original_broadcast = orchestrator.broadcast
    def record_broadcast(event_type: str, data: Dict[str, Any]) -> None:
        events.append((event_type, data))
        original_broadcast(event_type, data)
    orchestrator.broadcast = record_broadcast

    try:
        job = JobState(
            job_id="job-trunc-lifecycle",
            filename="sample_trunc.png",
            file_path=sample_png,
            page_count=2,
            status=JobStatus.UPLOADED,
        )
        orchestrator.register_job(job)
        orchestrator.enqueue("job-trunc-lifecycle")

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job("job-trunc-lifecycle")
            if j and j.status in (JobStatus.PARTIAL, JobStatus.SUCCESS, JobStatus.FAILED):
                break
            time.sleep(0.02)

        j = orchestrator.get_job("job-trunc-lifecycle")
        assert j is not None
        assert j.status == JobStatus.PARTIAL
        assert j.error == "Output truncated on page(s) 1 (hit token limit)"

        completed_events = [data for evt, data in events if evt == "completed"]
        assert len(completed_events) == 1
        comp = completed_events[0]
        assert comp["job_id"] == "job-trunc-lifecycle"
        assert comp["status"] == "partial"
        assert comp["truncated"] is True
        assert comp["truncated_pages"] == [1]
        assert comp["status_note"] == "Output truncated on page(s) 1 (hit token limit)"
    finally:
        orchestrator.stop()


def test_orchestrator_worker_loop_full_success_lifecycle(tmp_path: Path) -> None:
    """Verify worker loop handles successful results, broadcasting status, truncated=False, and empty notes."""
    sample_png = tmp_path / "sample_success.png"
    sample_png.write_bytes(_create_sample_png_bytes())

    orchestrator = WebOrchestrator(engine=MockEngine())
    events: List[Tuple[str, Dict[str, Any]]] = []
    original_broadcast = orchestrator.broadcast
    def record_broadcast(event_type: str, data: Dict[str, Any]) -> None:
        events.append((event_type, data))
        original_broadcast(event_type, data)
    orchestrator.broadcast = record_broadcast

    try:
        job = JobState(
            job_id="job-succ-lifecycle",
            filename="sample_success.png",
            file_path=sample_png,
            page_count=1,
            status=JobStatus.UPLOADED,
        )
        orchestrator.register_job(job)
        orchestrator.enqueue("job-succ-lifecycle")

        deadline = time.time() + 5.0
        while time.time() < deadline:
            j = orchestrator.get_job("job-succ-lifecycle")
            if j and j.status in (JobStatus.SUCCESS, JobStatus.FAILED):
                break
            time.sleep(0.02)

        j = orchestrator.get_job("job-succ-lifecycle")
        assert j is not None
        assert j.status == JobStatus.SUCCESS

        completed_events = [data for evt, data in events if evt == "completed"]
        assert len(completed_events) == 1
        comp = completed_events[0]
        assert comp["job_id"] == "job-succ-lifecycle"
        assert comp["status"] == "success"
        assert comp["truncated"] is False
        assert comp["truncated_pages"] == []
        assert comp["status_note"] is None
    finally:
        orchestrator.stop()
