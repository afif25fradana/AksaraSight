"""Core domain logic, models, and orchestration for OCR-LLM-Local."""

from .models import (
    JobConfig,
    JobStatus,
    OCRResult,
    OutputFormat,
    PageResult,
    PROMPT_PRESETS,
)
from .pipeline import (
    CorruptDocumentError,
    EmptyDocumentError,
    EncryptedDocumentError,
    ExtractedPage,
    FilePreflightError,
    PipelineError,
    UnsupportedFormatError,
    check_preflight,
    ingest,
    is_pdf,
)

__all__ = [
    "JobConfig",
    "JobStatus",
    "OCRResult",
    "OutputFormat",
    "PageResult",
    "PROMPT_PRESETS",
    "CorruptDocumentError",
    "EmptyDocumentError",
    "EncryptedDocumentError",
    "ExtractedPage",
    "FilePreflightError",
    "PipelineError",
    "UnsupportedFormatError",
    "check_preflight",
    "ingest",
    "is_pdf",
]
