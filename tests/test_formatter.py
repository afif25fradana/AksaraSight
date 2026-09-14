"""Unit tests for output formatting and artifact saving (core/formatter.py)."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from core.formatter import (
    WINDOWS_RESERVED_NAMES,
    format_output,
    resolve_unique_stem,
    sanitize_export_path,
    sanitize_filename_stem,
    save_artifacts,
)
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat, PageResult


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def sample_ocr_result() -> OCRResult:
    result = OCRResult(
        file_path="reports/financial_audit.pdf",
        pages=[
            PageResult(
                page_num=1,
                markdown="# Financial Report 2026\nQuarterly Revenue: $1.2M",
                raw_json={"id": "cmpl-1"},
                latency=0.3,
                status=JobStatus.SUCCESS,
            ),
            PageResult(
                page_num=2,
                markdown="## Expenses Breakdown\nOperational Cost: $400K",
                raw_json={"id": "cmpl-2"},
                latency=0.25,
                status=JobStatus.SUCCESS,
            ),
        ],
        total_duration=0.55,
        status=JobStatus.SUCCESS,
    )
    return result


# ==============================================================================
# Format Output Tests
# ==============================================================================

def test_format_output_markdown_only(sample_ocr_result: OCRResult) -> None:
    outputs = format_output(sample_ocr_result, OutputFormat.MARKDOWN)

    assert "markdown" in outputs
    assert "json" not in outputs
    assert "# Financial Report 2026" in outputs["markdown"]
    assert "## Expenses Breakdown" in outputs["markdown"]
    assert "---" in outputs["markdown"]


def test_format_output_json_only(sample_ocr_result: OCRResult) -> None:
    outputs = format_output(sample_ocr_result, OutputFormat.JSON)

    assert "json" in outputs
    assert "markdown" not in outputs

    parsed = json.loads(outputs["json"])
    assert parsed["file_path"] == "reports/financial_audit.pdf"
    assert parsed["status"] == "SUCCESS"
    assert parsed["page_count"] == 2


def test_format_output_both(sample_ocr_result: OCRResult) -> None:
    outputs = format_output(sample_ocr_result, OutputFormat.BOTH)

    assert "markdown" in outputs
    assert "json" in outputs
    assert "# Financial Report 2026" in outputs["markdown"]
    assert json.loads(outputs["json"])["page_count"] == 2


# ==============================================================================
# Save Artifacts Tests
# ==============================================================================

def test_save_artifacts_default_stem_from_file_path(
    sample_ocr_result: OCRResult,
    tmp_path: Path,
) -> None:
    config = JobConfig(output_format=OutputFormat.BOTH)
    saved = save_artifacts(sample_ocr_result, config, output_dir=tmp_path)

    expected_md = tmp_path / "financial_audit.md"
    expected_json = tmp_path / "financial_audit.json"

    assert saved["markdown"] == expected_md.resolve()
    assert saved["json"] == expected_json.resolve()

    assert expected_md.exists()
    assert expected_json.exists()

    md_content = expected_md.read_text(encoding="utf-8")
    assert "# Financial Report 2026" in md_content

    json_data = json.loads(expected_json.read_text(encoding="utf-8"))
    assert json_data["status"] == "SUCCESS"


def test_save_artifacts_custom_base_name_and_format_markdown_only(
    sample_ocr_result: OCRResult,
    tmp_path: Path,
) -> None:
    config = JobConfig(output_format=OutputFormat.MARKDOWN)
    saved = save_artifacts(
        sample_ocr_result,
        config,
        output_dir=tmp_path,
        base_name="custom_export_name",
    )

    assert "markdown" in saved
    assert "json" not in saved

    expected_md = tmp_path / "custom_export_name.md"
    assert saved["markdown"] == expected_md.resolve()
    assert expected_md.exists()
    assert not (tmp_path / "custom_export_name.json").exists()


def test_save_artifacts_in_memory_fallback_stem(tmp_path: Path) -> None:
    result = OCRResult(
        file_path="<in-memory>",
        pages=[PageResult(page_num=1, markdown="In-memory page", status=JobStatus.SUCCESS)],
    )
    config = JobConfig(output_format=OutputFormat.JSON)

    saved = save_artifacts(result, config, output_dir=tmp_path)
    expected_json = tmp_path / "ocr_result.json"

    assert saved["json"] == expected_json.resolve()
    assert expected_json.exists()


# ==============================================================================
# Filename Stem Sanitization Tests (Finding 1.2)
# ==============================================================================

@pytest.mark.parametrize(
    ("raw_stem", "expected"),
    [
        ("report:january*2026?", "report_january_2026_"),
        ("path/to\\bad|name<test>", "path_to_bad_name_test_"),
        ("trailing_dots....", "trailing_dots"),
        ("trailing_spaces   ", "trailing_spaces"),
        ("trailing_dots_and_spaces. . . ", "trailing_dots_and_spaces"),
        ("   ", "ocr_result"),
        ("....", "ocr_result"),
        ("CON", "_CON"),
        ("con", "_con"),
        ("PRN", "_PRN"),
        ("aux", "_aux"),
        ("NUL", "_NUL"),
        ("com1", "_com1"),
        ("COM9", "_COM9"),
        ("lpt1", "_lpt1"),
        ("LPT9", "_LPT9"),
    ],
)
def test_sanitize_filename_stem(raw_stem: str, expected: str) -> None:
    assert sanitize_filename_stem(raw_stem) == expected


# ==============================================================================
# Unique Collision Resolution Tests (Finding 1.1)
# ==============================================================================

def test_resolve_unique_stem_with_existing_disk_files(tmp_path: Path) -> None:
    # Pre-create disk files
    (tmp_path / "report.md").write_text("existing", encoding="utf-8")
    (tmp_path / "report_2.json").write_text("{}", encoding="utf-8")

    stem = resolve_unique_stem("report", output_dir=tmp_path)
    assert stem == "report_3"


def test_resolve_unique_stem_with_batch_used_stems(tmp_path: Path) -> None:
    used_stems = set()
    stem1 = resolve_unique_stem("invoice", output_dir=tmp_path, used_stems=used_stems)
    assert stem1 == "invoice"
    assert "invoice" in used_stems

    stem2 = resolve_unique_stem("invoice", output_dir=tmp_path, used_stems=used_stems)
    assert stem2 == "invoice_2"
    assert "invoice_2" in used_stems

    stem3 = resolve_unique_stem("invoice", output_dir=tmp_path, used_stems=used_stems)
    assert stem3 == "invoice_3"
    assert "invoice_3" in used_stems


def test_save_artifacts_avoids_clobbering_existing_disk_files(
    sample_ocr_result: OCRResult,
    tmp_path: Path,
) -> None:
    config = JobConfig(output_format=OutputFormat.MARKDOWN)

    # First save
    saved1 = save_artifacts(sample_ocr_result, config, output_dir=tmp_path)
    assert saved1["markdown"] == (tmp_path / "financial_audit.md").resolve()

    # Second save with same result (without used_stems) should still avoid overwriting
    saved2 = save_artifacts(sample_ocr_result, config, output_dir=tmp_path)
    assert saved2["markdown"] == (tmp_path / "financial_audit_2.md").resolve()

    assert (tmp_path / "financial_audit.md").exists()
    assert (tmp_path / "financial_audit_2.md").exists()


# ==============================================================================
# Path Privacy Export Sanitization Tests (Finding 4.1)
# ==============================================================================

def test_sanitize_export_path_relative_to_base_and_cwd(tmp_path: Path) -> None:
    """Verify sanitize_export_path relativizes within base_dir or cwd."""
    sub_file = tmp_path / "batches" / "scan1.pdf"

    # Relativize against explicit base_dir
    sanitized = sanitize_export_path(sub_file, base_dir=tmp_path)
    assert sanitized == "batches/scan1.pdf"

    # In-memory marker preserved
    assert sanitize_export_path("<in-memory>") == "<in-memory>"
    assert sanitize_export_path("<bytes>") == "<bytes>"
    assert sanitize_export_path("") == ""


def test_save_artifacts_path_privacy_sanitization(tmp_path: Path) -> None:
    """Verify save_artifacts sanitizes file_path in exported JSON by default without mutating OCRResult."""
    raw_path = tmp_path / "private_user_dir" / "secret_doc.pdf"
    result = OCRResult(
        file_path=str(raw_path),
        pages=[PageResult(page_num=1, markdown="Secret", status=JobStatus.SUCCESS)],
    )
    config = JobConfig(output_format=OutputFormat.JSON)

    # 1. Default (sanitize_path=True) with custom base_dir
    saved = save_artifacts(
        result,
        config,
        output_dir=tmp_path / "out",
        base_dir=tmp_path / "private_user_dir",
    )
    exported_json = json.loads(saved["json"].read_text(encoding="utf-8"))
    assert exported_json["file_path"] == "secret_doc.pdf"

    # Verify OCRResult internal data model was NOT mutated
    assert result.file_path == str(raw_path)
    assert result.to_dict()["file_path"] == str(raw_path)

    # 2. Explicit sanitize_path=False preserves absolute path
    saved_raw = save_artifacts(
        result,
        config,
        output_dir=tmp_path / "out_raw",
        sanitize_path=False,
    )
    exported_raw_json = json.loads(saved_raw["json"].read_text(encoding="utf-8"))
    assert exported_raw_json["file_path"] == str(raw_path)


def test_save_artifacts_atomic_write_preserves_existing_on_error(
    sample_ocr_result: OCRResult,
    tmp_path: Path,
) -> None:
    """Verify save_artifacts writes atomically and unlinks .tmp without corrupting existing file on error (C-6)."""
    config = JobConfig(output_format=OutputFormat.BOTH)

    # 1. Clean run writes files atomically
    saved = save_artifacts(sample_ocr_result, config, output_dir=tmp_path)
    md_file = saved["markdown"]
    json_file = saved["json"]
    assert md_file.exists()
    assert json_file.exists()
    assert not list(tmp_path.glob("*.tmp"))

    orig_md_content = md_file.read_text(encoding="utf-8")

    # 2. Simulate write_text failure on next save
    real_write_text = Path.write_text

    def failing_write_text(self, data, *args, **kwargs):
        if str(self).endswith(".tmp"):
            raise OSError("Simulated disk error during temp write")
        return real_write_text(self, data, *args, **kwargs)

    with patch.object(Path, "write_text", side_effect=failing_write_text, autospec=True):
        with pytest.raises(OSError, match="Simulated disk error"):
            save_artifacts(sample_ocr_result, config, output_dir=tmp_path)

    # Verify original file was not corrupted and no lingering .tmp files remain
    assert md_file.read_text(encoding="utf-8") == orig_md_content
    assert not list(tmp_path.glob("*.tmp"))



