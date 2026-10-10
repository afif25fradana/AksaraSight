"""Headless queue orchestrator for the AksaraSight Web UI spike."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import queue
import threading
from typing import Any, AsyncIterator, Dict, Optional, Set, Tuple

from core.client import ServerOfflineError
from core.engine import OCREngine
from core.models import JobStatus as CoreJobStatus, OCRResult, PageResult

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job status lifecycle states in web orchestrator."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class JobState:
    """State tracking model for an extraction job."""

    job_id: str
    filename: str
    file_path: Path
    status: JobStatus = JobStatus.QUEUED
    page_count: int = 0
    current_page: int = 0
    pages_data: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    result: Optional[OCRResult] = None
    error: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


class WebOrchestrator:
    """Coordinates headless extraction queues and broadcasts real-time SSE events."""

    def __init__(self, engine: OCREngine) -> None:
        self.engine = engine
        self.jobs: Dict[str, JobState] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._subscribers: Set[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="AksaraSight-WebWorker"
        )
        self._worker_thread.start()

    def register_job(self, job: JobState) -> None:
        """Register a newly uploaded job in the orchestrator registry."""
        with self._lock:
            self.jobs[job.job_id] = job

    def get_job(self, job_id: str) -> Optional[JobState]:
        """Retrieve a job by its unique identifier."""
        with self._lock:
            return self.jobs.get(job_id)

    def remove_job(self, job_id: str) -> Optional[JobState]:
        """Cancel and remove a job from the registry."""
        with self._lock:
            job = self.jobs.pop(job_id, None)
        if job:
            job.cancel_event.set()
        return job

    def enqueue(self, job_id: str) -> None:
        """Enqueue an existing job for processing."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(f"Job '{job_id}' not found")
            job.status = JobStatus.QUEUED
        self._queue.put(job_id)

    def cancel(self, job_id: str) -> bool:
        """Signal cooperative cancellation for a job."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            job.cancel_event.set()
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                self.broadcast("cancelled", {"job_id": job.job_id})
            return True

    def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast an event payload to all active SSE subscriber queues."""
        payload = {"event": event_type, "data": data}
        with self._lock:
            dead = []
            for entry in list(self._subscribers):
                q, loop = entry
                if loop.is_closed():
                    dead.append(entry)
                else:
                    try:
                        loop.call_soon_threadsafe(q.put_nowait, payload)
                    except RuntimeError:
                        dead.append(entry)
            for entry in dead:
                self._subscribers.discard(entry)

    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe to broadcast events, yielding event dictionaries."""
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        entry = (q, loop)
        with self._lock:
            self._subscribers.add(entry)
        try:
            while not self._stop_event.is_set():
                try:
                    msg = await q.get()
                    yield msg
                except asyncio.CancelledError:
                    break
        finally:
            with self._lock:
                self._subscribers.discard(entry)

    def stop(self) -> None:
        """Signal worker thread and subscribers to stop."""
        self._stop_event.set()
        self._queue.put("")

    def _worker_loop(self) -> None:
        """Background thread executing queued jobs sequentially."""
        while not self._stop_event.is_set():
            try:
                job_id = self._queue.get()
            except Exception:
                break

            if self._stop_event.is_set() or not job_id:
                break

            with self._lock:
                job = self.jobs.get(job_id)
            if not job:
                continue

            if job.cancel_event.is_set():
                job.status = JobStatus.CANCELLED
                self.broadcast("cancelled", {"job_id": job.job_id})
                continue

            job.status = JobStatus.PROCESSING
            self.broadcast(
                "started",
                {
                    "job_id": job.job_id,
                    "filename": job.filename,
                    "pages": job.page_count,
                },
            )

            def on_progress(page_num: int, total_pages: int, page_res: PageResult) -> None:
                job.current_page = page_num
                tokens = 0
                if page_res.raw_json and isinstance(page_res.raw_json, dict):
                    usage = page_res.raw_json.get("usage", {})
                    if isinstance(usage, dict):
                        tokens = usage.get("total_tokens", 0)
                text = page_res.markdown or ""
                latency = getattr(page_res, "latency", 0.0)
                truncated = getattr(page_res, "truncated", False)

                job.pages_data[page_num] = {
                    "text": text,
                    "latency": latency,
                    "tokens": tokens,
                    "truncated": truncated,
                }
                self.broadcast(
                    "page_progress",
                    {
                        "job_id": job.job_id,
                        "page_number": page_num,
                        "total_pages": total_pages,
                        "text": text,
                        "latency": latency,
                        "tokens": tokens,
                        "truncated": truncated,
                    },
                )

            try:
                result = self.engine.process_document(
                    source=job.file_path,
                    cancel_token=job.cancel_event,
                    progress_callback=on_progress,
                )
                job.result = result

                if job.cancel_event.is_set() or getattr(result, "status", None) == CoreJobStatus.CANCELLED:
                    job.status = JobStatus.CANCELLED
                    self.broadcast("cancelled", {"job_id": job.job_id})
                elif getattr(result, "status", None) == CoreJobStatus.FAILED and not result.pages:
                    job.status = JobStatus.FAILED
                    job.error = result.error or "Document processing failed"
                    self.broadcast("failed", {"job_id": job.job_id, "error": job.error})
                else:
                    job.status = JobStatus.SUCCESS
                    self.broadcast(
                        "completed",
                        {
                            "job_id": job.job_id,
                            "pages": job.page_count,
                        },
                    )
            except ServerOfflineError as e:
                job.status = JobStatus.FAILED
                job.error = str(e)
                self.broadcast("failed", {"job_id": job.job_id, "error": str(e)})
            except Exception as e:
                logger.exception("Unexpected error processing job %s", job.job_id)
                job.status = JobStatus.FAILED
                job.error = str(e)
                self.broadcast("failed", {"job_id": job.job_id, "error": str(e)})
