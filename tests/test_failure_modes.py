"""Failure-injection regression tests for OCR pipeline collaborators.

Ensures that an arbitrary failure from any major collaborator surfaces as a
user-visible FAILED/PARTIAL status with a non-empty error message, never a
silent swallow or an uncaught crash that loses sibling work. Recommended by
the B1–B5 audit round as a permanent regression net.

Each test injects a different exception type (RuntimeError) than the specific
bugs already fixed, so it tests the safety net's shape rather than duplicating
existing per-bug regression coverage.
"""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
import pypdfium2 as pdfium
import pytest

from config.settings import Settings
from core.client import ClientError, ServerOfflineError, VisionClient
from core.engine import OCREngine
from core.models import JobConfig, JobStatus, OCRResult, PageResult
from core.pipeline import ExtractedPage, PipelineError
from tests.fixture_helpers import load_real_glm_ocr_response


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=VisionClient)
    client.complete.return_value = (
        "# Recognized\nSome text.",
        load_real_glm_ocr_response(content="# Recognized\nSome text.", cmpl_id="fm-ok"),
        0.1,
        False,
    )
    return client


@pytest.fixture
def three_page_pdf(tmp_path: Path) -> Path:
    pdf = pdfium.PdfDocument.new()
    for _ in range(3):
        pdf.new_page(width=200, height=200)
    path = tmp_path / "three_page.pdf"
    pdf.save(path)
    pdf.close()
    return path


# ==============================================================================
# 1. VisionClient.complete() — arbitrary non-ClientError exception mid-batch
# ==============================================================================

def test_failure_isolation_client_arbitrary_exception_mid_batch(
    three_page_pdf: Path,
    mock_client: MagicMock,
) -> None:
    """An arbitrary RuntimeError from complete() on page 2 must not crash the
    process. Since RuntimeError is not a ClientError subclass, it escapes the
    per-page ClientError handler and hits the top-level except-Exception in
    process_document, producing a doc-level FAILED with page 1's work preserved."""
    mock_client.complete.side_effect = [
        (
            "Page 1 OK",
            load_real_glm_ocr_response(content="Page 1 OK", cmpl_id="fm-1"),
            0.1,
            False,
        ),
        RuntimeError("Arbitrary runtime failure in inference"),
    ]

    engine = OCREngine(client=mock_client)
    result = engine.process_document(three_page_pdf)

    # RuntimeError from complete() is NOT a ClientError, so it escapes the
    # per-page handler and is caught by the top-level except Exception.
    assert result.status == JobStatus.FAILED
    assert result.error is not None
    assert "Arbitrary runtime failure" in result.error
    # Page 1 was already appended before the crash
    assert len(result.pages) >= 1
    assert result.pages[0].status == JobStatus.SUCCESS
    assert result.pages[0].markdown == "Page 1 OK"


# ==============================================================================
# 2. VisionClient.complete() — ClientError (non-offline) mid-batch
# ==============================================================================

def test_failure_isolation_client_error_mid_batch(
    three_page_pdf: Path,
    mock_client: MagicMock,
) -> None:
    """A ClientError on page 2 of 3 marks that page FAILED but pages 1 and 3
    succeed, producing PARTIAL status with a non-empty per-page error."""
    mock_client.complete.side_effect = [
        (
            "Page 1 OK",
            load_real_glm_ocr_response(content="Page 1 OK", cmpl_id="fm-1"),
            0.1,
            False,
        ),
        ClientError("Injected client error on page 2"),
        (
            "Page 3 OK",
            load_real_glm_ocr_response(content="Page 3 OK", cmpl_id="fm-3"),
            0.1,
            False,
        ),
    ]

    engine = OCREngine(client=mock_client)
    result = engine.process_document(three_page_pdf)

    assert result.status == JobStatus.PARTIAL
    assert len(result.pages) == 3

    assert result.pages[0].status == JobStatus.SUCCESS
    assert result.pages[0].markdown == "Page 1 OK"

    assert result.pages[1].status == JobStatus.FAILED
    assert result.pages[1].error is not None
    assert len(result.pages[1].error) > 0
    assert "Injected client error" in result.pages[1].error

    assert result.pages[2].status == JobStatus.SUCCESS
    assert result.pages[2].markdown == "Page 3 OK"


# ==============================================================================
# 3. VisionClient.complete() — ServerOfflineError aborts batch
# ==============================================================================

def test_failure_isolation_client_offline_mid_batch(
    three_page_pdf: Path,
    mock_client: MagicMock,
) -> None:
    """ServerOfflineError on page 2 aborts remaining pages. Page 1 work is
    preserved, result is FAILED with non-empty error, and aborted flag is set."""
    mock_client.complete.side_effect = [
        (
            "Page 1 OK",
            load_real_glm_ocr_response(content="Page 1 OK", cmpl_id="fm-1"),
            0.1,
            False,
        ),
        ServerOfflineError("Injected: backend went offline"),
    ]

    engine = OCREngine(client=mock_client)
    result = engine.process_document(three_page_pdf)

    assert result.status == JobStatus.FAILED
    assert result.aborted is True
    assert result.error is not None
    assert len(result.error) > 0
    assert "Injected: backend went offline" in result.error

    # Page 1 preserved, page 2 marked failed, page 3 never attempted
    assert len(result.pages) == 2
    assert result.pages[0].status == JobStatus.SUCCESS
    assert result.pages[1].status == JobStatus.FAILED
    assert mock_client.complete.call_count == 2


# ==============================================================================
# 4. pipeline.ingest() — PipelineError during ingestion
# ==============================================================================

def test_failure_isolation_pipeline_error_raises(mock_client: MagicMock) -> None:
    """A PipelineError from ingest() produces doc FAILED with 0 pages and a
    non-empty error message."""
    engine = OCREngine(client=mock_client)

    with patch(
        "core.engine.ingest",
        side_effect=PipelineError("Injected pipeline pre-flight failure"),
    ):
        result = engine.process_document("fake_document.pdf")

    assert result.status == JobStatus.FAILED
    assert result.error is not None
    assert len(result.error) > 0
    assert "Injected pipeline pre-flight failure" in result.error
    assert len(result.pages) == 0
    mock_client.complete.assert_not_called()


# ==============================================================================
# 5. pipeline.ingest() — arbitrary RuntimeError during ingestion
# ==============================================================================

def test_failure_isolation_pipeline_unexpected_raises(mock_client: MagicMock) -> None:
    """An unexpected RuntimeError from ingest() is caught by the top-level
    except-Exception handler, producing doc FAILED with a descriptive error."""
    engine = OCREngine(client=mock_client)

    with patch(
        "core.engine.ingest",
        side_effect=RuntimeError("Injected unexpected ingestion crash"),
    ):
        result = engine.process_document("fake_document.pdf")

    assert result.status == JobStatus.FAILED
    assert result.error is not None
    assert len(result.error) > 0
    assert "Injected unexpected ingestion crash" in result.error
    assert len(result.pages) == 0
    mock_client.complete.assert_not_called()


# ==============================================================================
# 6. Pipeline rasterization — per-page failure via ExtractedPage.error
# ==============================================================================

def test_failure_isolation_rasterization_page_failure(mock_client: MagicMock) -> None:
    """A page yielded with error from the pipeline marks that page FAILED but
    sibling pages proceed normally, producing PARTIAL status."""
    pages = [
        ExtractedPage(page_num=1, total_pages=3, image_b64="data:image/jpeg;base64,abc"),
        ExtractedPage(page_num=2, total_pages=3, error="Injected rasterization failure on page 2"),
        ExtractedPage(page_num=3, total_pages=3, image_b64="data:image/jpeg;base64,def"),
    ]

    engine = OCREngine(client=mock_client)

    with patch("core.engine.ingest", return_value=iter(pages)):
        result = engine.process_document("fake_multipage.pdf")

    assert result.status == JobStatus.PARTIAL
    assert len(result.pages) == 3

    assert result.pages[0].status == JobStatus.SUCCESS
    assert result.pages[1].status == JobStatus.FAILED
    assert result.pages[1].error is not None
    assert "Injected rasterization failure" in result.pages[1].error
    assert result.pages[2].status == JobStatus.SUCCESS

    # Client only called for pages 1 and 3 (page 2 had no image)
    assert mock_client.complete.call_count == 2


# ==============================================================================
# 7. Progress callback — exception doesn't affect processing
# ==============================================================================

def test_failure_isolation_progress_callback_raises(
    three_page_pdf: Path,
    mock_client: MagicMock,
) -> None:
    """An exception thrown by the progress_callback must never crash or alter
    engine document processing. All 3 pages should succeed despite the callback
    raising on every invocation."""
    def exploding_callback(page_num: int, total_pages: int, page_result) -> None:
        raise RuntimeError("Injected callback explosion")

    engine = OCREngine(client=mock_client)
    result = engine.process_document(
        three_page_pdf,
        progress_callback=exploding_callback,
    )

    assert result.status == JobStatus.SUCCESS
    assert len(result.pages) == 3
    assert all(p.status == JobStatus.SUCCESS for p in result.pages)
    assert mock_client.complete.call_count == 3


# ==============================================================================
# 8. CLI batch loop — process_document raises, sibling docs continue
# ==============================================================================

@patch("cli.main.OCREngine")
@patch("cli.main.Settings.from_env")
def test_failure_isolation_cli_batch_document_crash(
    mock_settings_from_env: MagicMock,
    mock_engine_cls: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When process_document raises an arbitrary exception on one document in a
    CLI batch, the loop must continue processing remaining documents and exit
    with code 2 (partial failure), not crash."""
    from cli.main import main

    mock_settings_from_env.return_value = Settings()

    in_dir = tmp_path / "inputs"
    out_dir = tmp_path / "outputs"
    in_dir.mkdir()
    out_dir.mkdir()

    bad_file = in_dir / "01_crash.png"
    good_file = in_dir / "02_ok.png"
    bad_file.write_bytes(b"bad")
    good_file.write_bytes(b"good")

    ok_result = OCRResult(
        file_path=str(good_file),
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1, markdown="# Good doc", status=JobStatus.SUCCESS)],
    )

    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = [
        RuntimeError("Injected process_document crash"),
        ok_result,
    ]
    mock_engine_cls.return_value = mock_engine

    exit_code = main([str(in_dir), "-o", str(out_dir)])

    assert exit_code == 2
    assert mock_engine.process_document.call_count == 2

    captured = capsys.readouterr()
    assert "Injected process_document crash" in captured.err
    assert "02_ok.png" in captured.out


# ==============================================================================
# 9. Error message integrity — str(error) doesn't itself throw
# ==============================================================================

def test_failure_error_messages_are_safe_strings(
    three_page_pdf: Path,
    mock_client: MagicMock,
) -> None:
    """Verify that error messages produced by failure isolation are safe strings:
    non-empty, serializable, and calling str() / repr() on them doesn't throw.
    This is the class of bug that B2's NameError-in-error-message exposed."""
    mock_client.complete.side_effect = [
        ClientError("Error with special chars: <>&\"'\\n\\t"),
        ServerOfflineError("Offline error with unicode: café résumé"),
        ClientError(""),  # Empty error message edge case
    ]

    engine = OCREngine(client=mock_client)
    result = engine.process_document(three_page_pdf)

    for page in result.pages:
        if page.status == JobStatus.FAILED:
            # error exists, is a string, str()/repr() don't throw
            assert page.error is not None
            assert isinstance(page.error, str)
            _ = str(page.error)
            _ = repr(page.error)
            # Serialization to dict doesn't throw
            page_dict = page.to_dict()
            assert "error" in page_dict

    # Top-level result also serializes cleanly
    result_dict = result.to_dict()
    assert isinstance(result_dict, dict)
    _ = result.to_json()


# ==============================================================================
# 10. docx_export.build_docx() raises — CLI batch continues
# ==============================================================================

@patch("cli.main.OCREngine")
@patch("cli.main.Settings.from_env")
def test_failure_isolation_docx_export_raises(
    mock_settings_from_env: MagicMock,
    mock_engine_cls: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A RuntimeError from build_docx() during DOCX export for doc 1 must not
    crash the batch — doc 2 should still be exported successfully, exit code 2."""
    from cli.main import main

    mock_settings_from_env.return_value = Settings()

    in_dir = tmp_path / "inputs"
    out_dir = tmp_path / "outputs"
    in_dir.mkdir()
    out_dir.mkdir()

    f1 = in_dir / "01_bad_export.png"
    f2 = in_dir / "02_good_export.png"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")

    success_result_1 = OCRResult(
        file_path=str(f1),
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1, markdown="# Doc 1", status=JobStatus.SUCCESS)],
    )
    success_result_2 = OCRResult(
        file_path=str(f2),
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1, markdown="# Doc 2", status=JobStatus.SUCCESS)],
    )

    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = [success_result_1, success_result_2]
    mock_engine_cls.return_value = mock_engine

    with patch("cli.main.save_artifacts") as mock_save:
        mock_save.side_effect = [
            RuntimeError("Injected build_docx crash"),
            None,  # doc 2 saves fine
        ]
        exit_code = main([str(in_dir), "-o", str(out_dir), "-f", "docx"])

    assert exit_code == 2
    assert mock_engine.process_document.call_count == 2
    assert mock_save.call_count == 2

    captured = capsys.readouterr()
    assert "Error saving output for 01_bad_export.png" in captured.err
    assert "Injected build_docx crash" in captured.err
    # Doc 2 progress line still emitted
    assert "02_good_export.png" in captured.out


# ==============================================================================
# 11. format_output() raises — CLI batch continues
# ==============================================================================

@patch("cli.main.OCREngine")
@patch("cli.main.Settings.from_env")
def test_failure_isolation_format_output_raises(
    mock_settings_from_env: MagicMock,
    mock_engine_cls: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A RuntimeError from format_output() during stdout emit for doc 1 must
    not crash the batch — doc 2 should still be formatted and emitted."""
    from cli.main import main

    mock_settings_from_env.return_value = Settings()

    in_dir = tmp_path / "inputs"
    in_dir.mkdir()

    f1 = in_dir / "01_bad_fmt.png"
    f2 = in_dir / "02_good_fmt.png"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")

    result_1 = OCRResult(
        file_path=str(f1),
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1, markdown="# Doc 1", status=JobStatus.SUCCESS)],
    )
    result_2 = OCRResult(
        file_path=str(f2),
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1, markdown="# Doc 2", status=JobStatus.SUCCESS)],
    )

    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = [result_1, result_2]
    mock_engine_cls.return_value = mock_engine

    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    with patch("cli.main.save_artifacts") as mock_save:
        mock_save.side_effect = [
            RuntimeError("Injected format_output crash"),
            None,
        ]
        exit_code = main([str(in_dir), "-o", str(out_dir)])

    assert exit_code == 2
    assert mock_engine.process_document.call_count == 2

    captured = capsys.readouterr()
    assert "Error saving output for 01_bad_fmt.png" in captured.err
    assert "02_good_fmt.png" in captured.out


# ==============================================================================
# 12. save_artifacts() raises — CLI batch continues
# ==============================================================================

@patch("cli.main.OCREngine")
@patch("cli.main.Settings.from_env")
def test_failure_isolation_save_artifacts_raises(
    mock_settings_from_env: MagicMock,
    mock_engine_cls: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A disk-write OSError from save_artifacts() on doc 1 must not crash the
    batch — doc 2 writes successfully, exit code 2."""
    from cli.main import main

    mock_settings_from_env.return_value = Settings()

    in_dir = tmp_path / "inputs"
    out_dir = tmp_path / "outputs"
    in_dir.mkdir()
    out_dir.mkdir()

    f1 = in_dir / "01_write_fail.png"
    f2 = in_dir / "02_write_ok.png"
    f1.write_bytes(b"x")
    f2.write_bytes(b"x")

    result_1 = OCRResult(
        file_path=str(f1),
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1, markdown="# Doc 1", status=JobStatus.SUCCESS)],
    )
    result_2 = OCRResult(
        file_path=str(f2),
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1, markdown="# Doc 2", status=JobStatus.SUCCESS)],
    )

    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = [result_1, result_2]
    mock_engine_cls.return_value = mock_engine

    with patch("cli.main.save_artifacts") as mock_save:
        mock_save.side_effect = [
            OSError("Injected disk write failure"),
            None,
        ]
        exit_code = main([str(in_dir), "-o", str(out_dir)])

    assert exit_code == 2
    assert mock_save.call_count == 2

    captured = capsys.readouterr()
    assert "Error saving output for 01_write_fail.png" in captured.err
    assert "Injected disk write failure" in captured.err
    # Doc 2 still processed and its progress line emitted
    assert "02_write_ok.png" in captured.out
