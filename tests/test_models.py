"""Unit tests for core/models.py."""

from pathlib import Path
import json
import pytest
from core.models import (
    JobConfig,
    JobStatus,
    OCRResult,
    OutputFormat,
    PageResult,
    PROMPT_PRESETS,
)


def test_job_config_presets():
    """Verify standard prompt presets resolution."""
    config_text = JobConfig(prompt_mode="text")
    assert config_text.effective_prompt == "Text Recognition:"

    config_table = JobConfig(prompt_mode="table")
    assert config_table.effective_prompt == "Table Recognition:"

    config_formula = JobConfig(prompt_mode="formula")
    assert config_formula.effective_prompt == "Formula Recognition:"


def test_job_config_case_insensitivity():
    """Verify prompt_mode matches case-insensitively with whitespace stripped."""
    config = JobConfig(prompt_mode="  TABLE  ")
    assert config.effective_prompt == "Table Recognition:"


def test_job_config_custom_prompt_override():
    """Verify custom_prompt overrides any preset."""
    config = JobConfig(
        prompt_mode="text",
        custom_prompt="Extract only key-value pairs as JSON:",
    )
    assert config.effective_prompt == "Extract only key-value pairs as JSON:"


def test_job_config_invalid_prompt_mode_fail_fast():
    """Verify invalid prompt_mode without custom_prompt raises ValueError immediately."""
    config = JobConfig(prompt_mode="unsupported_mode")
    with pytest.raises(ValueError, match="Invalid prompt_mode: 'unsupported_mode'"):
        _ = config.effective_prompt


def test_page_result_defaults():
    """Verify PageResult default attributes."""
    page = PageResult(page_num=1)
    assert page.page_num == 1
    assert page.markdown == ""
    assert page.raw_json is None
    assert page.latency == 0.0
    assert page.status == JobStatus.SUCCESS
    assert page.error is None


def test_ocr_result_empty():
    """Verify OCRResult with no pages and no error resolves to SUCCESS."""
    result = OCRResult(file_path="sample.png")
    assert result.resolve_status() == JobStatus.SUCCESS
    assert result.markdown == ""


def test_ocr_result_file_level_error():
    """Verify document-level error resolves status to FAILED."""
    result = OCRResult(file_path="corrupt.png", error="Corrupt image header")
    assert result.resolve_status() == JobStatus.FAILED
    assert result.status == JobStatus.FAILED


def test_ocr_result_all_pages_success():
    """Verify multi-page all-success resolves to SUCCESS and aggregates markdown."""
    p1 = PageResult(page_num=1, markdown="# Page 1 Header", status=JobStatus.SUCCESS)
    p2 = PageResult(page_num=2, markdown="Page 2 Content", status=JobStatus.SUCCESS)
    result = OCRResult(file_path="doc.pdf", pages=[p1, p2])

    assert result.resolve_status() == JobStatus.SUCCESS
    assert result.status == JobStatus.SUCCESS
    assert result.markdown == "# Page 1 Header\n\n---\n\nPage 2 Content"


def test_ocr_result_all_pages_failed():
    """Verify multi-page all-failed resolves to FAILED."""
    p1 = PageResult(page_num=1, status=JobStatus.FAILED, error="Timeout")
    p2 = PageResult(page_num=2, status=JobStatus.FAILED, error="Connection refused")
    result = OCRResult(file_path="doc.pdf", pages=[p1, p2])

    assert result.resolve_status() == JobStatus.FAILED
    assert result.status == JobStatus.FAILED
    assert result.markdown == ""


def test_ocr_result_partial_success():
    """Verify mixed success/failure resolves to PARTIAL."""
    p1 = PageResult(page_num=1, markdown="Page 1 Text", status=JobStatus.SUCCESS)
    p2 = PageResult(page_num=2, status=JobStatus.FAILED, error="Inference failure")
    result = OCRResult(file_path="doc.pdf", pages=[p1, p2])

    assert result.resolve_status() == JobStatus.PARTIAL
    assert result.status == JobStatus.PARTIAL
    # Aggregate markdown should only include successful pages
    assert result.markdown == "Page 1 Text"


def test_ocr_result_to_dict_and_to_json():
    """Verify to_dict and to_json output structure without mutating status (pure CQS)."""
    p1 = PageResult(
        page_num=1,
        markdown="Text 1",
        latency=1.2,
        status=JobStatus.SUCCESS,
        raw_json={"choices": [{"message": {"content": "Text 1"}}]},
    )
    p2 = PageResult(
        page_num=2,
        markdown="",
        latency=0.3,
        status=JobStatus.FAILED,
        error="Failed page",
    )
    result = OCRResult(
        file_path=Path("sample.pdf"),
        pages=[p1, p2],
        total_duration=1.5,
    )

    # Before explicit status resolution, to_dict() reflects current status without mutating
    assert result.status == JobStatus.SUCCESS
    assert result.to_dict()["status"] == "SUCCESS"

    # Caller (e.g. engine.py) explicitly resolves status
    result.resolve_status()
    assert result.status == JobStatus.PARTIAL

    data = result.to_dict()
    assert data["file_path"] == "sample.pdf"
    assert data["status"] == "PARTIAL"
    assert data["total_duration"] == 1.5
    assert data["aborted"] is False
    assert data["page_count"] == 2
    assert len(data["pages"]) == 2
    assert data["pages"][0]["status"] == "SUCCESS"
    assert data["pages"][1]["status"] == "FAILED"
    assert data["pages"][1]["error"] == "Failed page"

    # Test JSON serialization
    json_str = result.to_json()
    parsed = json.loads(json_str)
    assert parsed["status"] == "PARTIAL"
    assert parsed["aborted"] is False
    assert parsed["cancelled"] is False
    assert parsed["pages"][0]["markdown"] == "Text 1"


def test_job_config_max_pages_validation():
    """Verify max_pages positive integer validation."""
    assert JobConfig(max_pages=5).max_pages == 5
    assert JobConfig(max_pages="3").max_pages == 3
    assert JobConfig(max_pages=None).max_pages is None

    with pytest.raises(ValueError, match="max_pages must be a positive integer"):
        JobConfig(max_pages=0)

    with pytest.raises(ValueError, match="max_pages must be a positive integer"):
        JobConfig(max_pages=-1)

    with pytest.raises(ValueError, match="max_pages must be a positive integer"):
        JobConfig(max_pages="abc")


def test_ocr_result_cancelled_resolution():
    """Verify OCRResult resolves to JobStatus.CANCELLED when cancelled=True."""
    p1 = PageResult(page_num=1, markdown="Page 1 Text", status=JobStatus.SUCCESS)
    result = OCRResult(
        file_path="multipage.pdf",
        pages=[p1],
        cancelled=True,
        error="Processing cancelled by user after page 1",
    )

    assert result.resolve_status() == JobStatus.CANCELLED
    assert result.status == JobStatus.CANCELLED
    assert result.cancelled is True

    data = result.to_dict()
    assert data["status"] == "CANCELLED"
    assert data["cancelled"] is True
    assert data["error"] == "Processing cancelled by user after page 1"

    parsed = json.loads(result.to_json())
    assert parsed["status"] == "CANCELLED"
    assert parsed["cancelled"] is True


def test_job_config_retain_images_default():
    """Verify JobConfig retain_images defaults to False and can be enabled."""
    cfg_default = JobConfig()
    assert cfg_default.retain_images is False

    cfg_custom = JobConfig(retain_images=True)
    assert cfg_custom.retain_images is True


def test_page_result_image_b64_default():
    """Verify PageResult image_b64 defaults to None and accepts base64 URL strings."""
    page = PageResult(page_num=1)
    assert page.image_b64 is None

    page_with_img = PageResult(page_num=1, image_b64="data:image/jpeg;base64,abc123xyz")
    assert page_with_img.image_b64 == "data:image/jpeg;base64,abc123xyz"


def test_ocr_result_to_dict_and_to_json_excludes_image_b64():
    """Verify to_dict and to_json exclude image_b64 to avoid bloating serialized outputs."""
    p1 = PageResult(
        page_num=1,
        markdown="Text 1",
        image_b64="data:image/jpeg;base64,very_large_base64_string",
    )
    result = OCRResult(file_path="sample.pdf", pages=[p1])

    dict_out = result.to_dict()
    assert "image_b64" not in dict_out
    assert "image_b64" not in dict_out["pages"][0]

    json_str = result.to_json()
    assert "image_b64" not in json_str
    assert "very_large_base64_string" not in json_str


def test_job_config_dpi_and_max_image_dimension_defaults():
    """Verify JobConfig defaults dpi and max_image_dimension to None."""
    cfg = JobConfig()
    assert cfg.dpi is None
    assert cfg.max_image_dimension is None


def test_job_config_dpi_and_max_image_dimension_valid():
    """Verify JobConfig accepts valid dpi and max_image_dimension."""
    cfg = JobConfig(dpi=150, max_image_dimension=1024)
    assert cfg.dpi == 150
    assert cfg.max_image_dimension == 1024


@pytest.mark.parametrize("bad_dpi", [0, -5, "bad"])
def test_job_config_bad_dpi_raises(bad_dpi):
    """Verify JobConfig raises ValueError on invalid dpi."""
    with pytest.raises(ValueError, match="dpi must be a positive integer"):
        JobConfig(dpi=bad_dpi)


@pytest.mark.parametrize("bad_dim", [0, 500, 9000, "bad"])
def test_job_config_bad_max_image_dimension_raises(bad_dim):
    """Verify JobConfig raises ValueError on invalid max_image_dimension."""
    with pytest.raises(ValueError, match="max_image_dimension must be an integer between 512 and 8192"):
        JobConfig(max_image_dimension=bad_dim)
