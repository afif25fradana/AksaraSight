"""Unit tests for OCREngine orchestration (core/engine.py)."""

import io
from pathlib import Path
import threading
from unittest.mock import MagicMock
from PIL import Image
import pypdfium2 as pdfium
import pytest

from config.settings import Settings
from core.client import (
    ClientError,
    ServerOfflineError,
    ServerTimeoutError,
    VisionClient,
)
from core.engine import OCREngine
from core.models import JobConfig, JobStatus
from core.pipeline import ExtractedPage
from tests.fixture_helpers import load_real_glm_ocr_response


# ==============================================================================
# Fixtures & Helpers
# ==============================================================================

@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=VisionClient)
    client.complete.return_value = (
        "# Page Title\nRecognized text.",
        load_real_glm_ocr_response(content="# Page Title\nRecognized text.", cmpl_id="test-cmpl"),
        0.25,
    )
    return client


@pytest.fixture
def sample_image_bytes() -> bytes:
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """Create a valid 3-page PDF for orchestration testing."""
    pdf = pdfium.PdfDocument.new()
    for _ in range(3):
        pdf.new_page(width=200, height=200)
    path = tmp_path / "test_doc_3pages.pdf"
    pdf.save(path)
    pdf.close()
    return path


# ==============================================================================
# Pipeline & Generator Laziness Isolation Tests
# ==============================================================================

def test_engine_catches_nonexistent_file_laziness_fix(mock_client: MagicMock) -> None:
    """Verify generator laziness: check_preflight runs and is caught cleanly."""
    engine = OCREngine(client=mock_client)
    nonexistent = "path_to_completely_missing_document_12345.pdf"

    result = engine.process_document(nonexistent)

    assert result.status == JobStatus.FAILED
    assert result.error is not None
    assert "not found" in result.error.lower()
    assert len(result.pages) == 0
    assert result.total_duration >= 0.0
    mock_client.complete.assert_not_called()


def test_engine_catches_zero_byte_file(tmp_path: Path, mock_client: MagicMock) -> None:
    zero_file = tmp_path / "empty.pdf"
    zero_file.write_bytes(b"")

    engine = OCREngine(client=mock_client)
    result = engine.process_document(zero_file)

    assert result.status == JobStatus.FAILED
    assert result.error is not None
    assert "empty" in result.error.lower() or "0 bytes" in result.error.lower()
    assert len(result.pages) == 0
    mock_client.complete.assert_not_called()



def test_engine_catches_unsupported_format(tmp_path: Path, mock_client: MagicMock) -> None:
    docx_file = tmp_path / "notes.docx"
    docx_file.write_bytes(b"PK\x03\x04Some fake docx bytes that are neither PDF nor image")

    engine = OCREngine(client=mock_client)
    result = engine.process_document(docx_file)

    assert result.status == JobStatus.FAILED
    assert result.error is not None
    assert "unsupported" in result.error.lower()
    assert len(result.pages) == 0
    mock_client.complete.assert_not_called()


# ==============================================================================
# Happy Path Orchestration Tests
# ==============================================================================

def test_engine_process_document_success(sample_pdf_path: Path, mock_client: MagicMock) -> None:
    engine = OCREngine(client=mock_client)
    config = JobConfig(prompt_mode="table")

    result = engine.process_document(sample_pdf_path, config=config)

    assert result.status == JobStatus.SUCCESS
    assert result.error is None
    assert len(result.pages) == 3
    assert mock_client.complete.call_count == 3

    # Check effective prompt was forwarded to client
    _, kwargs = mock_client.complete.call_args
    assert kwargs["prompt"] == "Table Recognition:"

    # Verify each page result
    for i, p in enumerate(result.pages, 1):
        assert p.page_num == i
        assert p.status == JobStatus.SUCCESS
        assert p.markdown == "# Page Title\nRecognized text."
        assert p.error is None
        assert p.latency == 0.25

    # Verify aggregate markdown
    assert "---" in result.markdown
    assert result.total_duration > 0.0




# ==============================================================================
# Per-Page Fault Isolation Tests (Partial Success)
# ==============================================================================

def test_engine_per_page_isolation_client_errors(sample_pdf_path: Path, mock_client: MagicMock) -> None:
    """Page 1 succeeds, Page 2 times out, Page 3 succeeds -> PARTIAL status."""
    mock_client.complete.side_effect = [
        ("Page 1 Markdown", load_real_glm_ocr_response(content="Page 1 Markdown", cmpl_id="cmpl-1"), 0.2),
        ServerTimeoutError("Request to backend timed out after 60s"),
        ("Page 3 Markdown", load_real_glm_ocr_response(content="Page 3 Markdown", cmpl_id="cmpl-3"), 0.3),
    ]

    engine = OCREngine(client=mock_client)
    result = engine.process_document(sample_pdf_path)

    assert result.status == JobStatus.PARTIAL
    assert len(result.pages) == 3

    assert result.pages[0].status == JobStatus.SUCCESS
    assert result.pages[0].markdown == "Page 1 Markdown"

    assert result.pages[1].status == JobStatus.FAILED
    assert "timed out" in str(result.pages[1].error)
    assert result.pages[1].markdown == ""

    assert result.pages[2].status == JobStatus.SUCCESS
    assert result.pages[2].markdown == "Page 3 Markdown"

    # Only successful pages are included in aggregate markdown
    assert "Page 1 Markdown" in result.markdown
    assert "Page 3 Markdown" in result.markdown


# ==============================================================================
# ServerOfflineError Fail-Fast Short-Circuit Tests
# ==============================================================================

def test_engine_server_offline_on_first_page_short_circuits(
    sample_pdf_path: Path,
    mock_client: MagicMock,
) -> None:
    """Server offline on page 1 aborts remaining pages with informative error."""
    mock_client.complete.side_effect = ServerOfflineError("Connection refused on port 8080")

    engine = OCREngine(client=mock_client)
    result = engine.process_document(sample_pdf_path)

    assert result.status == JobStatus.FAILED
    assert mock_client.complete.call_count == 1
    assert len(result.pages) == 1
    assert result.pages[0].status == JobStatus.FAILED

    # Error message explicitly details stopping page without claiming exact total count
    assert result.aborted is True
    assert result.error is not None
    assert "Inference backend offline on page 1" in result.error
    assert "remaining pages not attempted" in result.error
    assert "Connection refused on port 8080" in result.error


def test_engine_server_offline_mid_document_short_circuits(
    sample_pdf_path: Path,
    mock_client: MagicMock,
) -> None:
    """Server dies on page 2 after page 1 succeeds -> aborts page 3, marks FAILED."""
    mock_client.complete.side_effect = [
        ("Page 1 text", load_real_glm_ocr_response(content="Page 1 text", cmpl_id="cmpl-1"), 0.1),
        ServerOfflineError("Connection reset by peer"),
    ]

    engine = OCREngine(client=mock_client)
    result = engine.process_document(sample_pdf_path)

    # Status resolves to FAILED due to file-level abort error, while successful pages are preserved in pages
    assert result.status == JobStatus.FAILED
    assert result.aborted is True
    assert mock_client.complete.call_count == 2
    assert len(result.pages) == 2

    assert result.pages[0].status == JobStatus.SUCCESS
    assert result.pages[1].status == JobStatus.FAILED

    assert result.error is not None
    assert "Inference backend offline on page 2 (after 1 page(s) succeeded)" in result.error
    assert "remaining pages not attempted" in result.error
    assert "Connection reset by peer" in result.error





# ==============================================================================
# Pipeline-Yielded Page Failure Test
# ==============================================================================

def test_engine_handles_pipeline_rasterization_failure(mock_client: MagicMock) -> None:
    """Simulate a single page failing during rasterization from pipeline."""
    bad_page = ExtractedPage(page_num=1, error="Corrupt page raster stream")
    good_page = ExtractedPage(page_num=2, image_b64="data:image/jpeg;base64,abc")

    engine = OCREngine(client=mock_client)

    # Mock pipeline.ingest
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("core.engine.ingest", lambda *args, **kwargs: iter([bad_page, good_page]))
        result = engine.process_document("mock_multipage.pdf")

    assert result.status == JobStatus.PARTIAL
    assert len(result.pages) == 2
    assert result.pages[0].status == JobStatus.FAILED
    assert "Corrupt page raster stream" in str(result.pages[0].error)
    assert result.pages[1].status == JobStatus.SUCCESS
    # Client should only be called for the successful page
    assert mock_client.complete.call_count == 1


# ==============================================================================
# Page Limits & Cancellation Tests (Finding 3.1)
# ==============================================================================

def test_engine_max_pages_limit(sample_pdf_path: Path, mock_client: MagicMock) -> None:
    """Verify max_pages limits number of pages processed on multi-page documents."""
    engine = OCREngine(client=mock_client)
    config = JobConfig(max_pages=2)

    result = engine.process_document(sample_pdf_path, config=config)

    assert result.status == JobStatus.SUCCESS
    assert len(result.pages) == 2
    assert mock_client.complete.call_count == 2
    assert result.pages[0].page_num == 1
    assert result.pages[1].page_num == 2


def test_engine_inter_page_cancellation(sample_pdf_path: Path, mock_client: MagicMock) -> None:
    """Verify cancel_token halts processing cleanly between pages."""
    cancel_token = threading.Event()

    def complete_side_effect(*args, **kwargs):
        # Trigger cancellation after the first page completes
        cancel_token.set()
        return ("# Page 1 Text", load_real_glm_ocr_response(content="# Page 1 Text", cmpl_id="cmpl-1"), 0.1)

    mock_client.complete.side_effect = complete_side_effect

    engine = OCREngine(client=mock_client)
    result = engine.process_document(sample_pdf_path, cancel_token=cancel_token)

    assert result.status == JobStatus.CANCELLED
    assert result.cancelled is True
    assert result.error is not None
    assert "Processing cancelled by user after page 1" in result.error
    assert result.pages[0].status == JobStatus.SUCCESS
    assert result.pages[0].markdown == "# Page 1 Text"


# ==============================================================================
# Progress Callback & Image Retention Tests (Stage A)
# ==============================================================================

def test_engine_progress_callback_invoked(sample_pdf_path: Path, mock_client: MagicMock) -> None:
    """Verify progress_callback is called after each page with current_page, total_pages, and PageResult."""
    events = []

    def on_progress(current_page: int, total_pages: int, page_res) -> None:
        events.append((current_page, total_pages, page_res.page_num, page_res.status))

    engine = OCREngine(client=mock_client)
    result = engine.process_document(sample_pdf_path, progress_callback=on_progress)

    assert result.status == JobStatus.SUCCESS
    assert len(events) == 3
    assert events == [
        (1, 3, 1, JobStatus.SUCCESS),
        (2, 3, 2, JobStatus.SUCCESS),
        (3, 3, 3, JobStatus.SUCCESS),
    ]



def test_engine_progress_callback_exception_does_not_crash_pipeline(
    sample_pdf_path: Path,
    mock_client: MagicMock,
) -> None:
    """Verify an exception raised inside progress_callback does not abort engine processing."""
    def buggy_callback(current_page: int, total_pages: int, page_res) -> None:
        raise RuntimeError("Bug in user callback!")

    engine = OCREngine(client=mock_client)
    result = engine.process_document(sample_pdf_path, progress_callback=buggy_callback)

    assert result.status == JobStatus.SUCCESS
    assert len(result.pages) == 3


def test_engine_forwards_dpi_and_max_image_dimension(mock_client: MagicMock) -> None:
    """Verify OCREngine resolves and forwards dpi and max_image_dimension to ingest()."""
    from unittest.mock import patch

    settings = Settings(dpi=150, max_image_dimension=1024)
    engine = OCREngine(settings=settings, client=mock_client)

    with patch("core.engine.ingest", return_value=iter([])) as mock_ingest:
        # Default config: reads from settings
        engine.process_document("dummy.pdf")
        mock_ingest.assert_called_with("dummy.pdf", dpi=150, max_image_dimension=1024)

    with patch("core.engine.ingest", return_value=iter([])) as mock_ingest:
        # Explicit JobConfig override
        custom_cfg = JobConfig(dpi=200, max_image_dimension=4096)
        engine.process_document("dummy.pdf", config=custom_cfg)
        mock_ingest.assert_called_with("dummy.pdf", dpi=200, max_image_dimension=4096)


def test_engine_verify_backend_lifecycle_and_caching(mock_client: MagicMock) -> None:
    """Verify OCREngine.verify_backend caches result and respects invalidation."""
    engine = OCREngine(client=mock_client)
    assert engine._multimodal_verified is False

    # First call: runs probe
    engine.verify_backend()
    assert mock_client.verify_multimodal_support.call_count == 1
    assert engine._multimodal_verified is True

    # Second call: cached (no-op)
    engine.verify_backend()
    assert mock_client.verify_multimodal_support.call_count == 1

    # Force bypasses cache
    engine.verify_backend(force=True)
    assert mock_client.verify_multimodal_support.call_count == 2

    # Invalidation resets cache
    engine.invalidate_backend_verification()
    assert engine._multimodal_verified is False
    engine.verify_backend()
    assert mock_client.verify_multimodal_support.call_count == 3


def test_engine_verify_backend_raises_on_failure(mock_client: MagicMock) -> None:
    """Verify OCREngine.verify_backend raises error when client probe fails."""
    mock_client.verify_multimodal_support.side_effect = ClientError("Backend failed multimodal self-test")
    engine = OCREngine(client=mock_client)
    with pytest.raises(ClientError, match="Backend failed multimodal self-test"):
        engine.verify_backend()
    assert engine._multimodal_verified is False


# ==============================================================================
# End-to-End Loopback Server & Engine Lifecycle Integration Tests
# ==============================================================================

def test_engine_close_lifecycle() -> None:
    """Verify engine.close() safely releases client network session."""
    client = MagicMock(spec=VisionClient)
    engine = OCREngine(client=client)
    engine.close()
    assert client.close.call_count == 1

    # Safe to call multiple times or when client lacks close
    engine_no_client = OCREngine()
    engine_no_client.close()


def test_engine_real_loopback_e2e_pipeline_and_client_integration(tmp_path: Path) -> None:
    """Verify complete vertical stack: pypdfium2 PDF -> OCREngine -> VisionClient -> TCP loopback server."""
    import http.server
    import json
    from core.formatter import format_output, save_artifacts
    from core.models import OutputFormat

    class FakeOCRHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/health", "/v1/health"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            elif self.path in ("/models", "/v1/models"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data": [{"id": "GLM-OCR"}]}')
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            if self.path in ("/v1/chat/completions", "/chat/completions"):
                content_len = int(self.headers.get("Content-Length", 0))
                req_body = self.rfile.read(content_len)
                req_json = json.loads(req_body.decode("utf-8"))

                # Validate OpenAI wire structure generated by VisionClient
                assert "messages" in req_json
                assert "model" in req_json
                content_list = req_json["messages"][0]["content"]
                assert any(part.get("type") == "image_url" for part in content_list)

                # Send wire-accurate GLM-OCR completion
                resp_payload = load_real_glm_ocr_response(
                    content="# E2E Recognized Invoice\nInvoice content line.",
                    cmpl_id="e2e-cmpl-001",
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp_payload).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), FakeOCRHandler)
    server_port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        endpoint = f"http://127.0.0.1:{server_port}/v1"
        settings = Settings(
            local_endpoint=endpoint,
            timeout=5.0,
            max_retries=1,
        )
        client = VisionClient(settings=settings)
        engine = OCREngine(settings=settings, client=client)

        # 1. Verify backend probe over live loopback TCP socket
        engine.verify_backend()
        assert engine._multimodal_verified is True

        # 2. Process real 2-page PDF generated via pypdfium2
        pdf = pdfium.PdfDocument.new()
        pdf.new_page(width=300, height=400)
        pdf.new_page(width=300, height=400)
        test_pdf = tmp_path / "e2e_doc.pdf"
        pdf.save(str(test_pdf))
        pdf.close()

        result = engine.process_document(test_pdf)

        # 3. Assert end-to-end result validity
        assert result.status == JobStatus.SUCCESS
        assert len(result.pages) == 2
        for page in result.pages:
            assert page.status == JobStatus.SUCCESS
            assert page.markdown == "# E2E Recognized Invoice\nInvoice content line."
            assert page.raw_json is not None
            assert page.raw_json["id"] == "e2e-cmpl-001"
            assert page.raw_json["model"] == "GLM-OCR-Q8_0.gguf"
            assert page.raw_json["timings"]["prompt_n"] == 242
            assert page.latency > 0

        assert result.total_duration > 0

        # 4. Assert downstream formatting and disk persistence
        formatted = format_output(result, OutputFormat.BOTH)
        assert "# E2E Recognized Invoice" in formatted["markdown"]
        assert '"status": "SUCCESS"' in formatted["json"]

        out_dir = tmp_path / "e2e_out"
        out_dir.mkdir()
        save_artifacts(result, JobConfig(output_format=OutputFormat.BOTH), output_dir=out_dir)
        assert (out_dir / "e2e_doc.md").exists()
        assert (out_dir / "e2e_doc.json").exists()

        # 5. Engine cleanup
        engine.close()
    finally:
        server.shutdown()
        server.server_close()

