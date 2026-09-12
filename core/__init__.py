"""Core domain logic, models, and orchestration for OCR-LLM-Local."""

from .client import (
    BadRequestError,
    ClientError,
    ResponseParsingError,
    ServerError,
    ServerOfflineError,
    ServerTimeoutError,
    VisionClient,
    resolve_chat_endpoint,
)
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
    "BadRequestError",
    "ClientError",
    "CorruptDocumentError",
    "EmptyDocumentError",
    "EncryptedDocumentError",
    "ExtractedPage",
    "FilePreflightError",
    "JobConfig",
    "JobStatus",
    "OCRResult",
    "OutputFormat",
    "PageResult",
    "PipelineError",
    "PROMPT_PRESETS",
    "ResponseParsingError",
    "ServerError",
    "ServerOfflineError",
    "ServerTimeoutError",
    "UnsupportedFormatError",
    "VisionClient",
    "check_preflight",
    "ingest",
    "is_pdf",
    "resolve_chat_endpoint",
]

