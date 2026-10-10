"""Headless job orchestrator and event distribution for AksaraSight Web UI.

Manages FIFO execution of OCR document jobs on a dedicated worker thread,
supports cooperative cancellation between pages, and publishes live progress
events to async subscribers for SSE streaming.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple

from core.engine import OCREngine
from core.models import JobConfig, OCRResult, PageResult
import core.models as core_models

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Lifecycle status for a web document processing job."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"


@dataclass
class DocumentJob:
    """Represents a document submitted for OCR extraction.

    Attributes:
        job_id: Unique string identifier for the job.
        filename: Original user filename.
        file_path: Local path to the uploaded document on disk.
        status: Current lifecycle status of the job.
        current_page: Most recently processed page index (1-based).
        total_pages: Total number of pages in the document.
        pages_data: Mapping of page number to extraction metadata and text.
        result: Aggregated OCRResult upon completion.
        error: Error description if processing failed.
        cancel_event: Threading event signaled to request cooperative cancellation.
        created_at: Epoch timestamp when the job was uploaded.
        completed_at: Epoch timestamp when processing finished.
    """

    job_id: str
    filename: str
    file_path: Path
    status: JobStatus = JobStatus.QUEUED
    current_page: int = 0
    total_pages: int = 1
    pages_data: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    result: Optional[OCRResult] = None
    error: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class WebOrchestrator:
    """Headless queue coordinator running FIFO jobs via OCREngine."""

    def __init__(self, engine: Optional[OCREngine] = None) -> None:
        """Initialize the orchestrator with an engine instance."""
        self.engine: OCREngine = engine or OCREngine()
        self.jobs: Dict[str, DocumentJob] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._subscribers: Set[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._sub_lock = threading.Lock()

    def start(self) -> None:
        """Start the background worker thread if not already running."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="AksaraSight-WebWorker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("WebOrchestrator worker thread started")

    def stop(self, timeout: float = 3.0) -> None:
        """Signal the worker thread to stop and wait for it to join."""
        self._stop_event.set()
        # Request cancellation of all pending and running jobs
        for job in self.jobs.values():
            if job.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
                job.cancel_event.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=timeout)
            self._worker_thread = None
        logger.info("WebOrchestrator worker thread stopped")

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        """Register an async queue subscriber for SSE event distribution."""
        q: asyncio.Queue = asyncio.Queue()
        with self._sub_lock:
            self._subscribers.add((loop, q))
        return q

    def unsubscribe(self, subscriber: Tuple[asyncio.AbstractEventLoop, asyncio.Queue]) -> None:
        """Unregister an async subscriber."""
        with self._sub_lock:
            self._subscribers.discard(subscriber)

    def publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish a lifecycle event to all subscribed SSE client queues."""
        payload = {"event": event_type, "data": data}
        with self._sub_lock:
            dead_subs = []
            for loop, q in self._subscribers:
                if loop.is_closed():
                    dead_subs.append((loop, q))
                    continue
                try:
                    loop.call_soon_threadsafe(q.put_nowait, payload)
                except Exception:
                    dead_subs.append((loop, q))
            for dead in dead_subs:
                self._subscribers.discard(dead)

    def register_job(self, job: DocumentJob) -> None:
        """Register an uploaded document job in the job store."""
        self.jobs[job.job_id] = job

    def enqueue_job(self, job_id: str) -> None:
        """Enqueue a registered job for background processing."""
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(f"Job {job_id} not found")
        job.status = JobStatus.QUEUED
        self._queue.put(job_id)
        logger.info(f"Enqueued job {job_id} ({job.filename})")

    def cancel_job(self, job_id: str) -> bool:
        """Cancel an in-flight or queued job cooperatively."""
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.cancel_event.set()
        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            self.publish_event("cancelled", {"job_id": job_id})
        return True

    def _worker_loop(self) -> None:
        """Main FIFO loop processing jobs sequentially."""
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            job = self.jobs.get(job_id)
            if not job:
                self._queue.task_done()
                continue

            # Check if cancelled before starting
            if job.cancel_event.is_set():
                job.status = JobStatus.CANCELLED
                self.publish_event("cancelled", {"job_id": job.job_id})
                self._queue.task_done()
                continue

            job.status = JobStatus.PROCESSING
            self.publish_event(
                "started",
                {
                    "job_id": job.job_id,
                    "filename": job.filename,
                    "total_pages": job.total_pages,
                },
            )

            def _on_progress(page_num: int, total: int, page_res: PageResult) -> None:
                page_info = {
                    "page_number": page_num,
                    "text": page_res.markdown,
                    "latency": page_res.latency,
                    "tokens": page_res.tokens,
                    "truncated": page_res.truncated,
                    "status": page_res.status.value,
                }
                job.pages_data[page_num] = page_info
                job.current_page = page_num
                self.publish_event(
                    "page_progress",
                    {
                        "job_id": job.job_id,
                        "total_pages": total,
                        **page_info,
                    },
                )

            try:
                res = self.engine.process_document(
                    source=job.file_path,
                    cancel_token=job.cancel_event,
                    progress_callback=_on_progress,
                )
                job.result = res

                if job.cancel_event.is_set() or res.status == core_models.JobStatus.CANCELLED:
                    job.status = JobStatus.CANCELLED
                    self.publish_event("cancelled", {"job_id": job.job_id})
                elif res.status == core_models.JobStatus.FAILED:
                    job.status = JobStatus.FAILED
                    job.error = res.error or "Extraction failed"
                    self.publish_event("failed", {"job_id": job.job_id, "error": job.error})
                else:
                    job.status = JobStatus.SUCCESS
                    job.completed_at = time.time()
                    self.publish_event(
                        "completed",
                        {
                            "job_id": job.job_id,
                            "total_pages": job.total_pages,
                            "duration": res.duration_seconds,
                        },
                    )
            except Exception as exc:
                logger.exception(f"Unexpected error processing job {job_id}")
                job.status = JobStatus.FAILED
                job.error = str(exc)
                self.publish_event("failed", {"job_id": job.job_id, "error": str(exc)})
            finally:
                self._queue.task_done()
