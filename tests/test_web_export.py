"""Tests for Web document export endpoints, output directory security, and artifact persistence."""

import io
import json
from pathlib import Path
import time
from typing import Any, Dict, Optional, Tuple
from unittest.mock import patch

from PIL import Image

from config.settings import Settings
from core.client import ClientError
from core.engine import OCREngine
from core.models import JobStatus as CoreJobStatus, OCRResult, PageResult
from web.app import create_app
from web.orchestrator import JobState, JobStatus, WebOrchestrator
from tests.web_fixtures import (
    AsgiClient,
    MockEngine,
)


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
    assert md_item["localPath"] == "report.md"

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

        # Disallowed file extensions inside out_dir -> 400
        evil_exe = out_dir / "evil.exe"
        evil_exe.write_text("fake binary", encoding="utf-8")
        status, _, body = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=json.dumps({"path": "evil.exe"}).encode("utf-8"),
        )
        assert status == 400
        assert "Target file extension '.exe' is not permitted" in json.loads(body.decode("utf-8"))["detail"]

        notes_txt = out_dir / "notes.txt"
        notes_txt.write_text("notes", encoding="utf-8")
        status, _, body = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=json.dumps({"path": "notes.txt"}).encode("utf-8"),
        )
        assert status == 400
        assert "Target file extension '.txt' is not permitted" in json.loads(body.decode("utf-8"))["detail"]

        # Subdirectory target inside out_dir -> 400 (only files permitted when path is provided)
        subdir = out_dir / "subdir"
        subdir.mkdir(exist_ok=True)
        status, _, _ = client.post(
            "/api/output/open",
            headers={"content-type": "application/json"},
            body=json.dumps({"path": "subdir"}).encode("utf-8"),
        )
        assert status == 400

        # Windows Explorer quoting check: verify command string format for paths with spaces
        spaces_file = out_dir / "sample document with spaces.docx"
        spaces_file.write_text("spaces", encoding="utf-8")
        with patch("sys.platform", "win32"), patch("subprocess.run") as mock_sub_run:
            status, _, _ = client.post(
                "/api/output/open",
                headers={"content-type": "application/json"},
                body=json.dumps({"path": "sample document with spaces.docx"}).encode("utf-8"),
            )
            assert status == 200
            mock_sub_run.assert_called_once_with(
                f'explorer.exe /select,"{spaces_file.resolve()}"',
                check=False,
                timeout=10,
            )


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


def test_export_json_path_sanitization_avoids_upload_leak(tmp_path: Path) -> None:
    """Verify GET /api/documents/{id}/export?format=json does not leak absolute upload directory."""
    out_dir = tmp_path / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    orchestrator = WebOrchestrator(engine=MockEngine())
    app = create_app(upload_dir=tmp_path, output_dir=out_dir, orchestrator=orchestrator)
    client = AsgiClient(app)

    try:
        secret_upload = tmp_path / "very_secret_user_dir" / "sensitive_doc.pdf"
        secret_upload.parent.mkdir(parents=True, exist_ok=True)
        secret_upload.write_bytes(b"%PDF-1.4 dummy")

        job_id = "test-export-sanitize-path"
        page = PageResult(page_num=1, markdown="Sample text", status=CoreJobStatus.SUCCESS)
        ocr_result = OCRResult(file_path=str(secret_upload.resolve()), pages=[page], status=CoreJobStatus.SUCCESS)
        job = JobState(
            job_id=job_id,
            filename="sensitive_doc.pdf",
            file_path=secret_upload,
            page_count=1,
            status=JobStatus.SUCCESS,
            result=ocr_result,
        )
        orchestrator.register_job(job)

        status, _, body = client.get(f"/api/documents/{job_id}/export?format=json")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert str(secret_upload) not in data["file_path"]
        assert str(Path.home().resolve()) not in data["file_path"]
        assert not Path(data["file_path"]).is_absolute()
        assert data["file_path"].endswith("sensitive_doc.pdf")
    finally:
        orchestrator.stop()


def test_export_filename_windows_reserved_names(tmp_path: Path) -> None:
    """Verify export endpoints sanitize Windows reserved DOS device names."""
    out_dir = tmp_path / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    orchestrator = WebOrchestrator(engine=MockEngine())
    app = create_app(upload_dir=tmp_path, output_dir=out_dir, orchestrator=orchestrator)
    client = AsgiClient(app)

    try:
        job_id = "test-export-con-stem"
        page = PageResult(page_num=1, markdown="Reserved device test", status=CoreJobStatus.SUCCESS)
        ocr_result = OCRResult(file_path="CON.pdf", pages=[page], status=CoreJobStatus.SUCCESS)
        job = JobState(
            job_id=job_id,
            filename="CON.pdf",
            file_path=tmp_path / "CON.pdf",
            page_count=1,
            status=JobStatus.SUCCESS,
            result=ocr_result,
        )
        orchestrator.register_job(job)

        status, headers, _ = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status == 200
        disposition = headers.get("content-disposition", "")
        assert "_CON.md" in disposition
        assert (out_dir / "_CON.md").exists()
    finally:
        orchestrator.stop()


def test_export_document_sets_sanitized_persist_error_header_on_write_failure(tmp_path: Path) -> None:
    """Verify write failure sets sanitized X-Output-Persist-Error without CRLF or host paths."""
    out_dir = tmp_path / "output_artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = WebOrchestrator(engine=MockEngine())
    app = create_app(output_dir=out_dir, orchestrator=orchestrator)
    client = AsgiClient(app)

    try:
        job_id = "test-export-fail-job"
        page = PageResult(
            page_num=1,
            markdown="Sample markdown",
            status=CoreJobStatus.SUCCESS,
        )
        ocr_result = OCRResult(
            file_path="sample.pdf",
            pages=[page],
            status=CoreJobStatus.SUCCESS,
        )
        job = JobState(
            job_id=job_id,
            filename="sample.pdf",
            file_path=tmp_path / "sample.pdf",
            page_count=1,
            status=JobStatus.SUCCESS,
            result=ocr_result,
        )
        orchestrator.register_job(job)

        target_out_file = out_dir / "sample.md"
        fake_home_leak = Path.home() / "secret_folder"
        with patch("pathlib.Path.write_bytes", side_effect=OSError(13, f"Disk write failure\r\nPrivate {target_out_file} at {fake_home_leak}")):
            status, headers, body = client.get(f"/api/documents/{job_id}/export?format=md")
            assert status == 200
            assert body.decode("utf-8") == "Sample markdown"
            assert "x-output-persist-error" in headers
            err_val = headers["x-output-persist-error"]
            assert "\r" not in err_val
            assert "\n" not in err_val
            assert "Private" in err_val
            assert "sample.md" in err_val
            assert str(target_out_file) not in err_val
            assert str(fake_home_leak) not in err_val
    finally:
        orchestrator.stop()


def test_export_document_failed_job_notice_sanitizes_path(tmp_path: Path) -> None:
    """Verify export_document sanitizes internal paths in notice for failed jobs."""
    out_dir = tmp_path / "output"
    upload_dir = tmp_path / "uploads"
    out_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = WebOrchestrator(engine=MockEngine())
    app = create_app(output_dir=out_dir, upload_dir=upload_dir, orchestrator=orchestrator)
    client = AsgiClient(app)

    try:
        job_id = "test-fail-notice-job"
        secret_dir = Path.home() / "secret_folder"
        raw_error = f"Ingestion error in {secret_dir / 'corrupt.pdf'}: Corrupted structure"
        job = JobState(
            job_id=job_id,
            filename="corrupt.pdf",
            file_path=secret_dir / "corrupt.pdf",
            page_count=1,
            status=JobStatus.FAILED,
            error=raw_error,
            pages_data={1: {"text": "Partial text"}},
        )
        orchestrator.register_job(job)

        status, _, body = client.get(f"/api/documents/{job_id}/export?format=md")
        assert status == 200
        content_str = body.decode("utf-8")
        assert "Incomplete extraction:" in content_str
        assert str(secret_dir) not in content_str
    finally:
        orchestrator.stop()
