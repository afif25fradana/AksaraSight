"""Serialization and disk persistence helpers for OCR document results."""

from pathlib import Path
import re
from typing import Dict, Optional, Union

from core.models import JobConfig, OCRResult, OutputFormat


def format_output(result: OCRResult, output_format: OutputFormat) -> Dict[str, str]:
    """Format an OCRResult into output strings according to the requested format.

    Reuses OCRResult.to_markdown() and OCRResult.to_json() without duplicating
    formatting or joining logic.

    Args:
        result: Aggregated document OCRResult instance.
        output_format: Target format (MARKDOWN, JSON, or BOTH).

    Returns:
        Dict[str, str]: Mapping of format name ('markdown', 'json') to serialized content.
    """
    outputs: Dict[str, str] = {}

    if output_format in (OutputFormat.MARKDOWN, OutputFormat.BOTH):
        outputs["markdown"] = result.to_markdown()

    if output_format in (OutputFormat.JSON, OutputFormat.BOTH):
        outputs["json"] = result.to_json()

    return outputs


def save_artifacts(
    result: OCRResult,
    config: JobConfig,
    output_dir: Union[str, Path],
    base_name: Optional[str] = None,
) -> Dict[str, Path]:
    """Persist formatted OCR outputs to disk files.

    Determines file stem from base_name or result.file_path, ensures the target
    directory exists, and writes the configured format artifacts as UTF-8 files.

    Args:
        result: Aggregated document OCRResult.
        config: Job configuration specifying target output_format.
        output_dir: Destination folder path.
        base_name: Optional explicit base filename stem without extension.

    Returns:
        Dict[str, Path]: Mapping of format name to absolute Path of each created file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if base_name:
        stem = base_name.strip()
    else:
        src_path = str(result.file_path)
        if src_path and src_path not in ("<in-memory>", "<bytes>", ""):
            stem = Path(src_path).stem
        else:
            stem = "ocr_result"

    # Sanitize stem for cross-platform filename safety
    safe_stem = re.sub(r'[<>:"/\\|?*]', "_", stem) or "ocr_result"

    formatted = format_output(result, config.output_format)
    saved_paths: Dict[str, Path] = {}

    if "markdown" in formatted:
        md_file = out_dir / f"{safe_stem}.md"
        md_file.write_text(formatted["markdown"], encoding="utf-8")
        saved_paths["markdown"] = md_file.resolve()

    if "json" in formatted:
        json_file = out_dir / f"{safe_stem}.json"
        json_file.write_text(formatted["json"], encoding="utf-8")
        saved_paths["json"] = json_file.resolve()

    return saved_paths
