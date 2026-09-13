import logging
from pathlib import Path
import threading
import time
from typing import Callable, Optional, Union

from config.settings import Settings
from core.client import ClientError, ServerOfflineError, VisionClient
from core.models import JobConfig, JobStatus, OCRResult, PageResult
from core.pipeline import PipelineError, ingest

logger = logging.getLogger(__name__)


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
        """Initialize the OCR engine with runtime settings and inference client.

        Args:
            settings: Optional Settings instance (defaults to Settings()).
            client: Optional VisionClient instance (defaults to new client configured from settings).
        """
        self.settings = settings or Settings()
        self.client = client or VisionClient(settings=self.settings)


    def process_document(
        self,
        source: Union[str, Path],
        config: Optional[JobConfig] = None,
        cancel_token: Optional[threading.Event] = None,
        progress_callback: Optional[Callable[[int, int, PageResult], None]] = None,
    ) -> OCRResult:
        """Process a single document file through the OCR pipeline.

        Execution Lifecycle:
        1. Ingestion: Reads the document via core.pipeline.ingest() generator.
        2. Per-Page Rasterization: PDF pages and multi-frame images are converted to base64 Data URLs.
        3. Inference Dispatch: Each page is sent to the local vision model via self.client.complete().
        4. Error Isolation: Failures on individual pages (timeout, 400/5xx, parsing) are recorded in
           PageResult with JobStatus.FAILED; processing continues for remaining pages. If the
           backend server is offline (ServerOfflineError), processing aborts immediately,
           logging the count of skipped pages in result.error.
        5. Cancellation Support: Checked between pages via cancel_token.
        6. Status Resolution: OCRResult.resolve_status() is called explicitly once at the end
           of document processing (CQS compliance).

        Args:
            source: Document file path (str | Path).
            config: Job configuration containing prompt mode, overrides, and target format.
            cancel_token: Optional threading.Event instance checked between document pages.
                NOTE ON IN-FLIGHT LATENCY: Cancellation is evaluated strictly between pages,
                not during an in-flight VisionClient.complete() HTTP request. Because network
                socket calls are blocking, setting this token while page inference is underway
                will have a short latency (until the current page response arrives) before
                processing cleanly halts.
            progress_callback: Optional callback invoked after each page completes
                (page_num, total_pages, page_result).

        Returns:
            OCRResult: Aggregated document result containing page results, status, and duration.
        """
        start_time = time.perf_counter()
        cfg = config or JobConfig()
        file_path = str(source)

        result = OCRResult(file_path=file_path)
        effective_dpi = cfg.dpi if cfg.dpi is not None else getattr(self.settings, "dpi", 100)
        effective_max_dim = (
            cfg.max_image_dimension
            if cfg.max_image_dimension is not None
            else getattr(self.settings, "max_image_dimension", 2048)
        )

        try:
            # Note: ingest() is a generator; validation and pre-flight execute
            # once iteration begins (on the first next() call). Wrapping the iteration
            # loop ensures all PipelineErrors are caught cleanly.
            for page in ingest(
                source,
                dpi=effective_dpi,
                max_image_dimension=effective_max_dim,
            ):
                # Page limit safeguard (Finding 3.1)
                if cfg.max_pages is not None and page.page_num > cfg.max_pages:
                    break

                # Cooperative cancellation check between pages
                if cancel_token is not None and cancel_token.is_set():
                    result.cancelled = True
                    result.error = f"Processing cancelled by user after page {len(result.pages)}"
                    break

                total_pages = getattr(page, "total_pages", 1)

                # Pipeline-level rasterization failure for this individual page
                if not page.is_success:
                    page_res = PageResult(
                        page_num=page.page_num,
                        status=JobStatus.FAILED,
                        error=page.error or "Unknown rasterization failure",
                    )
                    result.pages.append(page_res)
                else:
                    # Vision model inference for this page
                    try:
                        text, raw_json, latency = self.client.complete(
                            image_b64=page.image_b64,
                            prompt=cfg.effective_prompt,
                        )
                        page_res = PageResult(
                            page_num=page.page_num,
                            markdown=text,
                            raw_json=raw_json,
                            latency=latency,
                            status=JobStatus.SUCCESS,
                        )
                        result.pages.append(page_res)
                    except ServerOfflineError as exc:
                        # Fail-fast short-circuit: record failure for current page and abort
                        page_res = PageResult(
                            page_num=page.page_num,
                            status=JobStatus.FAILED,
                            error=str(exc),
                        )
                        result.pages.append(page_res)
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
                    except ClientError as exc:
                        # Per-page isolation for non-offline errors (timeout, 400, 5xx exhaustion, parsing)
                        page_res = PageResult(
                            page_num=page.page_num,
                            status=JobStatus.FAILED,
                            error=str(exc),
                        )
                        result.pages.append(page_res)

                # Thread-safe progress notification: isolated in its own error boundary so a callback
                # exception (e.g. GUI bug) can NEVER crash or alter engine document processing.
                if progress_callback is not None:
                    try:
                        progress_callback(page.page_num, total_pages, page_res)
                    except Exception as cb_exc:
                        logger.warning(
                            "OCREngine progress_callback raised an exception on page %d: %s",
                            page.page_num,
                            cb_exc,
                        )

                if result.aborted:
                    break

            if not result.pages and not result.error:
                result.error = "Document produced 0 extractable pages"

        except PipelineError as exc:
            # File-level ingestion failure (nonexistent file, permission denied, 0-byte, corrupt)
            result.error = str(exc)

        result.total_duration = time.perf_counter() - start_time
        result.resolve_status()
        return result

    def close(self) -> None:
        """Release underlying client network session and connection pool resources."""
        if self.client and hasattr(self.client, "close"):
            self.client.close()



