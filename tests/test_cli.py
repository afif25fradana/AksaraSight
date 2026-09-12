"""Unit and functional tests for the Command Line Interface (cli/main.py)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from cli.main import SUPPORTED_EXTENSIONS, discover_files, main
from core.models import JobStatus, OCRResult, OutputFormat, PageResult


# ==============================================================================
# Fixtures & Helpers
# ==============================================================================

@pytest.fixture
def dummy_png(tmp_path: Path) -> Path:
    p = tmp_path / "sample.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nDummyPNG")
    return p


@pytest.fixture
def dummy_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "sample.pdf"
    p.write_bytes(b"%PDF-1.4\nDummyPDF")
    return p


@pytest.fixture
def mock_success_result() -> OCRResult:
    return OCRResult(
        file_path="sample.png",
        pages=[
            PageResult(
                page_num=1,
                markdown="# Sample OCR Output\nRecognized text line.",
                status=JobStatus.SUCCESS,
            )
        ],
        total_duration=0.42,
        status=JobStatus.SUCCESS,
        aborted=False,
    )


# ==============================================================================
# Extension Discovery Tests
# ==============================================================================

def test_discover_files_explicit_whitelist(tmp_path: Path) -> None:
    # Supported
    (tmp_path / "img1.PNG").write_bytes(b"1")
    (tmp_path / "img2.jpg").write_bytes(b"2")
    (tmp_path / "doc.pdf").write_bytes(b"3")
    (tmp_path / "scan.tiff").write_bytes(b"4")
    (tmp_path / "photo.webp").write_bytes(b"5")

    # Unsupported
    (tmp_path / "notes.txt").write_bytes(b"6")
    (tmp_path / "archive.zip").write_bytes(b"7")
    (tmp_path / "report.docx").write_bytes(b"8")

    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()
    (sub_dir / "sub_doc.pdf").write_bytes(b"9")

    # Non-recursive
    files = discover_files(tmp_path, recursive=False)
    names = [f.name for f in files]
    assert sorted(names) == ["doc.pdf", "img1.PNG", "img2.jpg", "photo.webp", "scan.tiff"]

    # Recursive
    rec_files = discover_files(tmp_path, recursive=True)
    rec_names = [f.name for f in rec_files]
    assert sorted(rec_names) == ["doc.pdf", "img1.PNG", "img2.jpg", "photo.webp", "scan.tiff", "sub_doc.pdf"]


# ==============================================================================
# Single File Execution Tests
# ==============================================================================

@patch("cli.main.OCREngine")
def test_cli_single_file_stdout_markdown(
    mock_engine_cls: MagicMock,
    dummy_png: Path,
    mock_success_result: OCRResult,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_engine = MagicMock()
    mock_engine.process_document.return_value = mock_success_result
    mock_engine_cls.return_value = mock_engine

    exit_code = main([str(dummy_png)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "# Sample OCR Output" in captured.out
    assert "Recognized text line." in captured.out
    assert captured.err == ""


@patch("cli.main.OCREngine")
def test_cli_single_file_stdout_json_quiet_pipeable(
    mock_engine_cls: MagicMock,
    dummy_png: Path,
    mock_success_result: OCRResult,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_engine = MagicMock()
    mock_engine.process_document.return_value = mock_success_result
    mock_engine_cls.return_value = mock_engine

    exit_code = main([str(dummy_png), "-f", "json", "--quiet"])

    assert exit_code == 0
    captured = capsys.readouterr()
    # Output must be 100% parseable JSON with 0 prefix/suffix text
    parsed = json.loads(captured.out)
    assert parsed["status"] == "SUCCESS"
    assert parsed["pages"][0]["markdown"] == "# Sample OCR Output\nRecognized text line."
    assert captured.err == ""


@patch("cli.main.OCREngine")
def test_cli_single_file_save_to_output_dir(
    mock_engine_cls: MagicMock,
    dummy_png: Path,
    tmp_path: Path,
    mock_success_result: OCRResult,
) -> None:
    mock_engine = MagicMock()
    mock_engine.process_document.return_value = mock_success_result
    mock_engine_cls.return_value = mock_engine

    out_dir = tmp_path / "out"
    exit_code = main([str(dummy_png), "-o", str(out_dir), "-f", "both"])

    assert exit_code == 0
    assert (out_dir / "sample.md").exists()
    assert (out_dir / "sample.json").exists()


# ==============================================================================
# Fatal Configuration & Validation Tests (Exit Code 1)
# ==============================================================================

def test_cli_fatal_nonexistent_input_path(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["nonexistent_path_xyz.pdf"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error: Input path does not exist" in captured.err


def test_cli_fatal_directory_without_output_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(tmp_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error: -o/--output directory is required" in captured.err


def test_cli_fatal_directory_with_no_supported_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "file.txt").write_text("plain text")
    out_dir = tmp_path / "out"
    exit_code = main([str(tmp_path), "-o", str(out_dir)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error: No supported document files found" in captured.err


def test_cli_fatal_invalid_backend_override(
    dummy_png: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # argparse should reject invalid backend
    with pytest.raises(SystemExit) as exc:
        main([str(dummy_png), "--backend", "unknown-backend"])
    assert exc.value.code == 2


@patch("cli.main.OCREngine")
def test_cli_fatal_backend_offline_abort(
    mock_engine_cls: MagicMock,
    dummy_png: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_engine = MagicMock()
    offline_result = OCRResult(
        file_path=str(dummy_png),
        pages=[PageResult(page_num=1, status=JobStatus.FAILED, error="Connection refused")],
        status=JobStatus.FAILED,
        error="Inference backend offline on page 1: Connection refused",
        aborted=True,
    )
    mock_engine.process_document.return_value = offline_result
    mock_engine_cls.return_value = mock_engine

    exit_code = main([str(dummy_png)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Aborted: Inference backend offline" in captured.err


# ==============================================================================
# Batch Processing & Exit Code 2 (Partial/Failure) Tests
# ==============================================================================

@patch("cli.main.OCREngine")
def test_cli_batch_folder_all_success(
    mock_engine_cls: MagicMock,
    tmp_path: Path,
    mock_success_result: OCRResult,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.png").write_bytes(b"a")
    (docs_dir / "b.pdf").write_bytes(b"b")

    mock_engine = MagicMock()
    mock_engine.process_document.return_value = mock_success_result
    mock_engine_cls.return_value = mock_engine

    out_dir = tmp_path / "results"
    exit_code = main([str(docs_dir), "-o", str(out_dir)])

    assert exit_code == 0
    assert mock_engine.process_document.call_count == 2


@patch("cli.main.OCREngine")
def test_cli_batch_folder_partial_failure_exit_code_2(
    mock_engine_cls: MagicMock,
    tmp_path: Path,
    mock_success_result: OCRResult,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "1.png").write_bytes(b"1")
    (docs_dir / "2.png").write_bytes(b"2")

    failed_result = OCRResult(
        file_path="2.png",
        pages=[PageResult(page_num=1, status=JobStatus.FAILED, error="Timeout")],
        status=JobStatus.FAILED,
        error="Inference failure",
        aborted=False,
    )

    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = [mock_success_result, failed_result]
    mock_engine_cls.return_value = mock_engine

    out_dir = tmp_path / "results"
    exit_code = main([str(docs_dir), "-o", str(out_dir)])

    # Exit code 2 for partial failure
    assert exit_code == 2


# ==============================================================================
# Settings Override & Parameter Passing Test
# ==============================================================================

@patch("cli.main.OCREngine")
def test_cli_passes_settings_and_prompt_overrides(
    mock_engine_cls: MagicMock,
    dummy_png: Path,
    mock_success_result: OCRResult,
) -> None:
    mock_engine = MagicMock()
    mock_engine.process_document.return_value = mock_success_result
    mock_engine_cls.return_value = mock_engine

    exit_code = main([
        str(dummy_png),
        "--backend", "ollama",
        "--endpoint", "http://127.0.0.1:11434/v1",
        "-p", "table",
        "--prompt", "Custom OCR Table Prompt:",
    ])

    assert exit_code == 0
    mock_engine_cls.assert_called_once()
    _, init_kwargs = mock_engine_cls.call_args
    passed_settings = init_kwargs["settings"]
    assert passed_settings.backend == "ollama"
    assert passed_settings.local_endpoint == "http://127.0.0.1:11434/v1"

    _, proc_kwargs = mock_engine.process_document.call_args
    passed_config = proc_kwargs["config"]
    assert passed_config.prompt_mode == "table"
    assert passed_config.custom_prompt == "Custom OCR Table Prompt:"
    assert passed_config.effective_prompt == "Custom OCR Table Prompt:"


def test_cli_remote_endpoint_rejected_without_flag(
    dummy_png: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """Verify CLI exits with code 1 and error message if remote endpoint given without --allow-remote."""
    exit_code = main([
        str(dummy_png),
        "--endpoint", "http://192.168.1.100:8080/v1",
    ])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Configuration error: Security violation: Non-loopback endpoint" in captured.err


@patch("cli.main.OCREngine")
def test_cli_remote_endpoint_accepted_with_allow_remote_flag(
    mock_engine_cls: MagicMock,
    dummy_png: Path,
    mock_success_result: OCRResult,
    capsys: pytest.CaptureFixture,
) -> None:
    """Verify CLI accepts non-loopback endpoint when --allow-remote flag is specified and warns."""
    mock_engine = MagicMock()
    mock_engine.process_document.return_value = mock_success_result
    mock_engine_cls.return_value = mock_engine

    exit_code = main([
        str(dummy_png),
        "--endpoint", "http://192.168.1.100:8080/v1",
        "--allow-remote",
    ])
    assert exit_code == 0
    _, init_kwargs = mock_engine_cls.call_args
    passed_settings = init_kwargs["settings"]
    assert passed_settings.local_endpoint == "http://192.168.1.100:8080/v1"
    assert passed_settings.allow_remote is True
    captured = capsys.readouterr()
    assert "WARNING: Backend endpoint is non-loopback" in captured.err


@patch("cli.main.OCREngine")
def test_cli_batch_duplicate_filenames_no_overwrite(
    mock_engine_cls: MagicMock,
    tmp_path: Path,
) -> None:
    """Verify CLI batch processing with duplicate stems creates unique files instead of overwriting."""
    input_dir = tmp_path / "inputs"
    sub_a = input_dir / "sub_a"
    sub_b = input_dir / "sub_b"
    sub_a.mkdir(parents=True)
    sub_b.mkdir(parents=True)

    file_a = sub_a / "document.pdf"
    file_b = sub_b / "document.pdf"
    file_a.write_bytes(b"%PDF-1.4 dummy a")
    file_b.write_bytes(b"%PDF-1.4 dummy b")

    output_dir = tmp_path / "outputs"

    def fake_process_document(path, config=None):
        return OCRResult(
            file_path=str(path),
            pages=[PageResult(page_num=1, markdown=f"# Output for {path.parent.name}", status=JobStatus.SUCCESS)],
            status=JobStatus.SUCCESS,
        )

    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = fake_process_document
    mock_engine_cls.return_value = mock_engine

    exit_code = main([
        str(input_dir),
        "-r",
        "-o", str(output_dir),
        "-f", "markdown",
    ])

    assert exit_code == 0
    assert (output_dir / "document.md").exists()
    assert (output_dir / "document_2.md").exists()
    content_1 = (output_dir / "document.md").read_text(encoding="utf-8")
    content_2 = (output_dir / "document_2.md").read_text(encoding="utf-8")
    assert content_1 != content_2


