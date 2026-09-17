"""Serialization and disk persistence helpers for OCR document results."""

import dataclasses
import json
from pathlib import Path
import re
from typing import Dict, Optional, Set, Union

from core.docx_export import export_to_docx_bytes
from core.models import JobConfig, OCRResult, OutputFormat

# Reserved device names on Windows operating systems (case-insensitive)
WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})


def sanitize_filename_stem(stem: str) -> str:
    """Sanitize a file stem for cross-platform filesystem safety.

    - Replaces forbidden filesystem characters (< > : " / \\ | ? *) with underscores.
    - Strips trailing periods and spaces (which Windows NTFS silently discards or rejects).
    - Escapes Windows DOS device reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
      by prefixing with an underscore.
    - Falls back to 'ocr_result' if the stem becomes empty.

    Args:
        stem: Raw string stem candidate.

    Returns:
        str: Cleaned, safe filename stem.
    """
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", stem.strip())
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        cleaned = "ocr_result"

    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    return cleaned


def resolve_unique_stem(
    base_stem: str,
    output_dir: Union[str, Path],
    used_stems: Optional[Set[str]] = None,
) -> str:
    """Resolve a collision-free, cross-platform sanitized file stem.

    Guarantees no collisions with:
    1. Pre-existing files in output_dir (*.md and *.json).
    2. Other files exported in the current batch (via used_stems tracking set).

    Args:
        base_stem: Proposed filename stem.
        output_dir: Target destination folder.
        used_stems: Optional set of stems already claimed in this batch. Updated in-place.

    Returns:
        str: A safe, unique file stem.
    """
    out_dir = Path(output_dir)
    safe_base = sanitize_filename_stem(base_stem)
    stem = safe_base
    counter = 1

    tracked_stems = used_stems if used_stems is not None else set()

    while (
        stem in tracked_stems
        or (out_dir / f"{stem}.md").exists()
        or (out_dir / f"{stem}.json").exists()
        or (out_dir / f"{stem}.docx").exists()
    ):
        counter += 1
        stem = f"{safe_base}_{counter}"

    tracked_stems.add(stem)
    return stem


def sanitize_export_path(
    file_path: Union[str, Path],
    base_dir: Optional[Union[str, Path]] = None,
) -> str:
    """Sanitize a document file path for exported artifacts to avoid leaking user home paths.

    Attempts to relativize the path to base_dir (or Path.cwd()). If the path lies outside
    that base directory, attempts to relativize to Path.home() (stripping the OS username/home
    prefix), and falls back to Path(file_path).name if across drives or un-relativizable.

    Args:
        file_path: Raw source document path.
        base_dir: Optional reference directory to relativize against (defaults to Path.cwd()).

    Returns:
        str: Relativized and privacy-safe path representation using standard forward slashes.
    """
    raw = str(file_path)
    if not raw or raw in ("<in-memory>", "<bytes>"):
        return raw

    try:
        target = Path(file_path).resolve()
    except Exception:
        return Path(raw).name

    # 1. Try relative to base_dir or cwd
    try:
        ref_dir = Path(base_dir if base_dir is not None else Path.cwd()).resolve()
        return str(target.relative_to(ref_dir)).replace("\\", "/")
    except (ValueError, RuntimeError):
        pass

    # 2. Try relative to user home directory (strips C:/Users/<username>)
    try:
        home_dir = Path.home().resolve()
        return str(target.relative_to(home_dir)).replace("\\", "/")
    except (ValueError, RuntimeError):
        pass

    # 3. Fallback to bare filename if across drives or non-relativizable
    return target.name


def sanitize_export_error(
    error: Optional[str],
    file_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Union[str, Path]] = None,
) -> Optional[str]:
    """Sanitize an error string in exported JSON to avoid leaking local user home paths.

    Args:
        error: Raw error message string.
        file_path: Optional associated document path to match and relativize.
        base_dir: Optional reference directory for path relativization.

    Returns:
        Optional[str]: Sanitized error message without absolute user home paths.
    """
    if not error:
        return error

    sanitized = str(error)

    # 1. If file_path is provided, replace occurrences of its raw and resolved forms
    if file_path and str(file_path) not in ("<in-memory>", "<bytes>", ""):
        raw_str = str(file_path)
        sanitized_path = sanitize_export_path(file_path, base_dir=base_dir)

        variants = {raw_str, raw_str.replace("\\", "/"), raw_str.replace("/", "\\")}
        try:
            resolved_str = str(Path(file_path).resolve())
            variants.update({resolved_str, resolved_str.replace("\\", "/"), resolved_str.replace("/", "\\")})
        except Exception:
            pass

        for var in sorted(variants, key=len, reverse=True):
            if var and var in sanitized:
                sanitized = sanitized.replace(var, sanitized_path)

    # 2. Defense-in-depth: replace user home directory if still present
    try:
        home_dir = str(Path.home().resolve())
        if home_dir and home_dir in sanitized:
            sanitized = sanitized.replace(home_dir, "~")
        home_dir_fwd = home_dir.replace("\\", "/")
        if home_dir_fwd and home_dir_fwd in sanitized:
            sanitized = sanitized.replace(home_dir_fwd, "~")
    except Exception:
        pass

    return sanitized


def _reconstruct_sanitized_exception(
    exc: Exception,
    file_path: Optional[Union[str, Path]] = None,
    base_dir: Optional[Union[str, Path]] = None,
) -> Exception:
    """Reconstruct an exception with sanitized path representation without crashing or losing OSError attributes.

    For OSError / PermissionError / FileNotFoundError instances with standard (errno, strerror, filename)
    signatures, reconstructs with sanitized filename and message while preserving errno.
    For other exception types, attempts reconstruction with the sanitized string or safely falls back
    to OSError(sanitized_str) to prevent TypeError on custom exception signatures.
    """
    raw_str = str(exc)
    sanitized_str = sanitize_export_error(raw_str, file_path=file_path, base_dir=base_dir) or raw_str

    if isinstance(exc, OSError):
        errno_val = getattr(exc, "errno", None)
        strerror_val = getattr(exc, "strerror", None)
        filename_val = getattr(exc, "filename", None)
        if errno_val is not None and strerror_val is not None and filename_val is not None:
            sanitized_fn = sanitize_export_path(filename_val, base_dir=base_dir)
            sanitized_err = sanitize_export_error(strerror_val, file_path=file_path, base_dir=base_dir) or strerror_val
            try:
                # Reconstruct standard OS exception preserving errno, strerror, and sanitized filename
                new_exc = type(exc)(errno_val, sanitized_err, sanitized_fn)
                return new_exc
            except Exception:
                pass

    try:
        return type(exc)(sanitized_str)
    except Exception:
        return OSError(sanitized_str)


def format_output(
    result: OCRResult,
    output_format: OutputFormat,
    sanitize_path: bool = False,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Union[str, bytes]]:
    """Format an OCRResult into output strings or bytes according to the requested format.

    Reuses OCRResult.to_markdown(), OCRResult.to_json(), and export_to_docx_bytes()
    without duplicating formatting or joining logic.

    Args:
        result: Aggregated document OCRResult instance.
        output_format: Target format (MARKDOWN, JSON, BOTH, or DOCX).
        sanitize_path: If True, relativizes file_path in exported JSON and DOCX to avoid leaking
            local user home directories.
        base_dir: Optional reference directory for path relativization.

    Returns:
        Dict[str, Union[str, bytes]]: Mapping of format name ('markdown', 'json', 'docx')
            to serialized content (strings for markdown/json, binary bytes for docx).
    """
    outputs: Dict[str, Union[str, bytes]] = {}

    if output_format in (OutputFormat.MARKDOWN, OutputFormat.BOTH):
        outputs["markdown"] = result.markdown

    if output_format in (OutputFormat.JSON, OutputFormat.BOTH):
        if sanitize_path:
            data = result.to_dict()
            data["file_path"] = sanitize_export_path(result.file_path, base_dir=base_dir)
            if data.get("error"):
                data["error"] = sanitize_export_error(data["error"], file_path=result.file_path, base_dir=base_dir)
            for page_dict in data.get("pages", []):
                if page_dict.get("error"):
                    page_dict["error"] = sanitize_export_error(
                        page_dict["error"], file_path=result.file_path, base_dir=base_dir
                    )
            outputs["json"] = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            outputs["json"] = result.to_json()

    if output_format == OutputFormat.DOCX:
        if sanitize_path and result.error:
            sanitized_err = sanitize_export_error(result.error, file_path=result.file_path, base_dir=base_dir)
            sanitized_result = dataclasses.replace(result, error=sanitized_err)
            outputs["docx"] = export_to_docx_bytes(sanitized_result)
        else:
            outputs["docx"] = export_to_docx_bytes(result)

    return outputs


def save_artifacts(
    result: OCRResult,
    config: JobConfig,
    output_dir: Union[str, Path],
    base_name: Optional[str] = None,
    used_stems: Optional[Set[str]] = None,
    sanitize_path: bool = True,
    base_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Path]:
    """Persist formatted OCR outputs to disk files with collision safety.

    Determines file stem from base_name or result.file_path, ensures the target
    directory exists, guarantees collision-free unique stems, and writes the configured
    format artifacts as UTF-8 files (for text) or binary files (for docx).

    Args:
        result: Aggregated document OCRResult.
        config: Job configuration specifying target output_format.
        output_dir: Destination folder path.
        base_name: Optional explicit base filename stem without extension.
        used_stems: Optional set tracking stems allocated within an export batch.
        sanitize_path: Whether to relativize file_path in exported JSON (default True).
        base_dir: Optional reference directory for path relativization.

    Returns:
        Dict[str, Path]: Mapping of format name to absolute Path of each created file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if base_name:
        candidate_stem = base_name.strip()
    else:
        src_path = str(result.file_path)
        if src_path and src_path not in ("<in-memory>", "<bytes>", ""):
            candidate_stem = Path(src_path).stem
        else:
            candidate_stem = "ocr_result"

    safe_stem = resolve_unique_stem(candidate_stem, output_dir=out_dir, used_stems=used_stems)

    formatted = format_output(
        result,
        config.output_format,
        sanitize_path=sanitize_path,
        base_dir=base_dir,
    )
    saved_paths: Dict[str, Path] = {}

    if "markdown" in formatted:
        md_file = out_dir / f"{safe_stem}.md"
        temp_file = md_file.with_suffix(".md.tmp")
        try:
            temp_file.write_text(formatted["markdown"], encoding="utf-8")
            temp_file.replace(md_file)
        except Exception as exc:
            temp_file.unlink(missing_ok=True)
            if sanitize_path:
                raise _reconstruct_sanitized_exception(exc, file_path=result.file_path, base_dir=base_dir) from None
            raise
        saved_paths["markdown"] = md_file.resolve()

    if "json" in formatted:
        json_file = out_dir / f"{safe_stem}.json"
        temp_file = json_file.with_suffix(".json.tmp")
        try:
            temp_file.write_text(formatted["json"], encoding="utf-8")
            temp_file.replace(json_file)
        except Exception as exc:
            temp_file.unlink(missing_ok=True)
            if sanitize_path:
                raise _reconstruct_sanitized_exception(exc, file_path=result.file_path, base_dir=base_dir) from None
            raise
        saved_paths["json"] = json_file.resolve()

    if "docx" in formatted:
        docx_file = out_dir / f"{safe_stem}.docx"
        temp_file = docx_file.with_suffix(".docx.tmp")
        try:
            temp_file.write_bytes(formatted["docx"])
            temp_file.replace(docx_file)
        except Exception as exc:
            temp_file.unlink(missing_ok=True)
            if sanitize_path:
                raise _reconstruct_sanitized_exception(exc, file_path=result.file_path, base_dir=base_dir) from None
            raise
        saved_paths["docx"] = docx_file.resolve()

    return saved_paths
