"""Core OCR orchestration engine coordinating document ingestion and vision inference."""

from pathlib import Path
import time
from typing import Optional, Union

from config.settings import Settings
from core.client import ClientError, ServerOfflineError, VisionClient
from core.models import JobConfig, JobStatus, OCRResult, PageResult
from core.pipeline import PipelineError, ingest


class OCREngine:
    """Orchestrates end-to-end OCR processing for images and PDF documents.

    Coordinates document ingestion and rasterization via core.pipeline, dispatches
    page images to the local vision backend via core.client, and aggregates results
    into a structured OCRResult model.

    Attributes:
        settings: Application runtime configuration.
        client: Vision inference client communicating with the local backend.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[VisionClient] = None,
    ) -> None:
        """Initialize the OCR Engine.

        Args:
            settings: Runtime configuration settings. Defaults to Settings() if omitted.
            client: VisionClient instance. Created automatically if omitted.
        """
        self.settings = settings or Settings()
        self.client = client or VisionClient(self.settings)


    def process_document(
        self,
        source: Union[str, Path, bytes, bytearray, memoryview],
        config: Optional[JobConfig] = None,
        file_name: Optional[str] = None,
    ) -> OCRResult:
        """Process an entire document (image or PDF) and return an aggregated OCRResult.

        Orchestration steps:
        1. Pre-flight & Ingestion: Ingests pages as a stream from core.pipeline.ingest.
           PipelineError instances (missing file, zero-byte, encrypted, corrupt header)
           are caught at the document level, producing a failed OCRResult without crashing.
        2. Per-Page Inference: Pages are rendered to RGB base64 Data URLs and dispatched
           to the vision client with the effective prompt configured in JobConfig.
        3. Fault Isolation: Transient client/inference errors on one page record a failed
           PageResult for that page without aborting the remaining document.
        4. Fail-Fast Short-Circuit: If ServerOfflineError is encountered, the engine aborts
           immediately to avoid grinding through remaining pages against a dead server,
           logging the count of skipped pages in result.error.
        5. Status Resolution: OCRResult.resolve_status() is called explicitly once at the end
           of document processing (CQS compliance).

        Args:
            source: Document file path (str | Path) or raw byte buffer.
            config: Job configuration containing prompt mode, overrides, and target format.
            file_name: Optional display filename when source is provided as raw bytes.

        Returns:
            OCRResult: Aggregated document result containing page results, status, and duration.
        """
        start_time = time.perf_counter()
        cfg = config or JobConfig()

        if isinstance(source, (str, Path)):
            file_path = str(source)
        else:
            file_path = file_name or "<in-memory>"

        result = OCRResult(file_path=file_path)


        try:
            # Note: ingest() is a generator; validation and pre-flight execute
            # once iteration begins (on the first next() call). Wrapping the iteration
            # loop ensures all PipelineErrors are caught cleanly.
            for page in ingest(source):
                # Pipeline-level rasterization failure for this individual page
                if not page.is_success:
                    result.pages.append(
                        PageResult(
                            page_num=page.page_num,
                            status=JobStatus.FAILED,
                            error=page.error or "Unknown rasterization failure",
                        )
                    )
                    continue

                # Vision model inference for this page
                try:
                    text, raw_json, latency = self.client.complete(
                        image_b64=page.image_b64,
                        prompt=cfg.effective_prompt,
                    )
                    result.pages.append(
                        PageResult(
                            page_num=page.page_num,
                            markdown=text,
                            raw_json=raw_json,
                            latency=latency,
                            status=JobStatus.SUCCESS,
                        )
                    )
                except ServerOfflineError as exc:
                    # Fail-fast short-circuit: record failure for current page and abort
                    result.pages.append(
                        PageResult(
                            page_num=page.page_num,
                            status=JobStatus.FAILED,
                            error=str(exc),
                        )
                    )

                    result.aborted = True
                    succeeded = sum(1 for p in result.pages if p.status == JobStatus.SUCCESS)
                    if succeeded > 0:
                        result.error = (
                            f"Inference backend offline on page {page.page_num} "
                            f"(after {succeeded} page(s) succeeded); remaining pages not attempted: {exc}"
                        )
                    else:
                        result.error = (
                            f"Inference backend offline on page 1; remaining pages not attempted: {exc}"
                        )
                    break
                except ClientError as exc:
                    # Per-page isolation for non-offline errors (timeout, 400, 5xx exhaustion, parsing)
                    result.pages.append(
                        PageResult(
                            page_num=page.page_num,
                            status=JobStatus.FAILED,
                            error=str(exc),
                        )
                    )

            if not result.pages and not result.error:
                result.error = "Document produced 0 extractable pages"

        except PipelineError as exc:
            # File-level ingestion failure (nonexistent file, permission denied, 0-byte, corrupt)
            result.error = str(exc)

        result.total_duration = time.perf_counter() - start_time
        result.resolve_status()
        return result
