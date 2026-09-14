"""Core data models and type definitions for OCR pipeline."""

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

PROMPT_PRESETS: Dict[str, str] = {
    "text": "Text Recognition:",
    "table": "Table Recognition:",
    "formula": "Formula Recognition:",
}


class JobStatus(str, Enum):
    """Execution status for page extraction and document jobs."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"


class OutputFormat(str, Enum):
    """Supported serialization output formats."""

    MARKDOWN = "markdown"
    JSON = "json"
    BOTH = "both"


@dataclass
class JobConfig:
    """Configuration options for an individual OCR job.

    Attributes:
        output_format: Target format ('markdown', 'json', 'both').
        prompt_mode: Preset prompt selector ('text', 'table', 'formula').
        custom_prompt: Optional explicit prompt override that bypasses presets.
        max_pages: Optional upper limit on the number of pages processed per document.
    """

    output_format: OutputFormat = OutputFormat.MARKDOWN
    prompt_mode: str = "text"
    custom_prompt: Optional[str] = None
    max_pages: Optional[int] = None
    dpi: Optional[int] = None
    max_image_dimension: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if self.max_pages is not None:
            try:
                val = int(self.max_pages)
                if val <= 0:
                    raise ValueError
                object.__setattr__(self, "max_pages", val)
            except (ValueError, TypeError):
                raise ValueError(f"max_pages must be a positive integer, got: {self.max_pages}")

        if self.dpi is not None:
            try:
                val_dpi = int(self.dpi)
                if val_dpi <= 0:
                    raise ValueError
                object.__setattr__(self, "dpi", val_dpi)
            except (ValueError, TypeError):
                raise ValueError(f"dpi must be a positive integer, got: {self.dpi}")

        if self.max_image_dimension is not None:
            try:
                val_dim = int(self.max_image_dimension)
                if not (512 <= val_dim <= 8192):
                    raise ValueError
                object.__setattr__(self, "max_image_dimension", val_dim)
            except (ValueError, TypeError):
                raise ValueError(
                    f"max_image_dimension must be an integer between 512 and 8192, got: {self.max_image_dimension}"
                )

    @property
    def effective_prompt(self) -> str:
        """Resolve the effective prompt string.

        Returns:
            str: Custom prompt if provided, or the mapped preset string.

        Raises:
            ValueError: If prompt_mode is not in PROMPT_PRESETS and custom_prompt is None.
        """
        if self.custom_prompt:
            return self.custom_prompt

        mode_key = self.prompt_mode.strip().lower()
        if mode_key not in PROMPT_PRESETS:
            valid_modes = ", ".join(sorted(PROMPT_PRESETS.keys()))
            raise ValueError(
                f"Invalid prompt_mode: '{self.prompt_mode}'. Valid modes: {valid_modes}"
            )

        return PROMPT_PRESETS[mode_key]


@dataclass
class PageResult:
    """Extraction result for an individual document page.

    Attributes:
        page_num: 1-indexed page number.
        markdown: Parsed markdown content for this page.
        raw_json: Raw inference completion response from the local backend.
        latency: Time in seconds taken to process this page.
        status: Page processing outcome (SUCCESS or FAILED).
        error: Descriptive error message if processing failed.
    """

    page_num: int
    markdown: str = ""
    raw_json: Optional[Dict[str, Any]] = None
    latency: float = 0.0
    status: JobStatus = JobStatus.SUCCESS
    error: Optional[str] = None


@dataclass
class OCRResult:
    """Aggregated OCR result for a single document (image or PDF).

    Attributes:
        file_path: Source document path.
        pages: List of individual PageResult objects.
        total_duration: Total processing time in seconds across all pages.
        status: Overall document outcome (SUCCESS, PARTIAL, FAILED).
        error: File-level failure message (e.g. corrupt header, unreadable file).
    """

    file_path: str | Path
    pages: List[PageResult] = field(default_factory=list)
    total_duration: float = 0.0
    status: JobStatus = JobStatus.SUCCESS
    error: Optional[str] = None
    aborted: bool = False
    cancelled: bool = False

    def resolve_status(self) -> JobStatus:
        """Compute and update aggregate status based on file error, cancellation, and page outcomes.

        Rules:
        - If cancellation was requested: CANCELLED.
        - If document-level error is present: FAILED.
        - If no pages exist: FAILED.
        - If all pages succeeded: SUCCESS.
        - If all pages failed: FAILED.
        - If some pages succeeded and some failed: PARTIAL.

        Returns:
            JobStatus: The resolved status assigned to self.status.
        """
        if self.cancelled:
            self.status = JobStatus.CANCELLED
            return self.status

        if self.error:
            self.status = JobStatus.FAILED
            return self.status

        if not self.pages:
            self.status = JobStatus.FAILED
            return self.status

        success_count = sum(1 for p in self.pages if p.status == JobStatus.SUCCESS)
        if success_count == len(self.pages):
            self.status = JobStatus.SUCCESS
        elif success_count == 0:
            self.status = JobStatus.FAILED
        else:
            self.status = JobStatus.PARTIAL

        return self.status

    @property
    def markdown(self) -> str:
        """Aggregate markdown text across all successful pages, separated by horizontal rules."""
        page_mds = [
            p.markdown for p in self.pages
            if p.status == JobStatus.SUCCESS and p.markdown.strip()
        ]
        return "\n\n---\n\n".join(page_mds)


    def to_dict(self) -> Dict[str, Any]:
        """Export structured dictionary representation of the document result.

        Returns:
            Dict[str, Any]: Normalized document result dictionary.
        """
        return {
            "file_path": str(self.file_path),
            "status": self.status.value,
            "total_duration": self.total_duration,
            "error": self.error,
            "aborted": self.aborted,
            "cancelled": self.cancelled,
            "page_count": len(self.pages),
            "pages": [
                {
                    "page_num": p.page_num,
                    "status": p.status.value,
                    "latency": p.latency,
                    "markdown": p.markdown,
                    "error": p.error,
                    "raw_json": p.raw_json,
                }
                for p in self.pages
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize structured dictionary to formatted JSON string.

        Args:
            indent: Indentation spaces for JSON formatting (default: 2).

        Returns:
            str: JSON string.
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
