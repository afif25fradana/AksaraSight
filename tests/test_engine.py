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
    BadRequestError,
    ClientError,
    ServerOfflineError,
    ServerTimeoutError,
    VisionClient,
)
from core.engine import OCREngine
from core.models import JobConfig, JobStatus, OutputFormat
from core.pipeline import ExtractedPage


# ==============================================================================
# Fixtures & Helpers
# ==============================================================================

@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=VisionClient)
    client.complete.return_value = ("# Page Title\nRecognized text.", {"id": "test-cmpl"}, 0.25)
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
        ("Page 1 Markdown", {"id": "1"}, 0.2),
        ServerTimeoutError("Request to backend timed out after 60s"),
        ("Page 3 Markdown", {"id": "3"}, 0.3),
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
        ("Page 1 text", {"id": "1"}, 0.1),
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
        return ("# Page 1 Text", {"id": "1"}, 0.1)

    mock_client.complete.side_effect = complete_side_effect

    engine = OCREngine(client=mock_client)
    result = engine.process_document(sample_pdf_path, cancel_token=cancel_token)

    assert result.status == JobStatus.CANCELLED
    assert result.cancelled is True
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
