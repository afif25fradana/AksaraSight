"""Core domain logic, models, and orchestration for OCR-LLM-Local."""

from .models import (
    JobConfig,
    JobStatus,
    OCRResult,
    OutputFormat,
    PageResult,
    PROMPT_PRESETS,
)

__all__ = [
    "JobConfig",
    "JobStatus",
    "OCRResult",
    "OutputFormat",
    "PageResult",
    "PROMPT_PRESETS",
]
