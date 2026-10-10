"""Headless queue orchestrator for the AksaraSight Web UI spike."""

import asyncio
import copy
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import queue
import threading
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple
import uuid

from core.client import ServerOfflineError
from core.engine import OCREngine
from core.models import JobConfig, JobStatus as CoreJobStatus, OCRResult, PageResult

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job status lifecycle states in web orchestrator."""

    UPLOADED = "UPLOADED"
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
    status: JobStatus = JobStatus.UPLOADED
    page_count: int = 0
    current_page: int = 0
    pages_data: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    result: Optional[OCRResult] = None
    error: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    prompt_mode: str = "text"


class WebOrchestrator:
    """Coordinates headless extraction queues and broadcasts real-time SSE events."""

    def __init__(self, engine: OCREngine) -> None:
        self.engine = engine
        self.jobs: Dict[str, JobState] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._subscribers: Set[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="AksaraSight-WebWorker"
        )
        self._worker_thread.start()

    def is_processing(self) -> bool:
        """Return True if any job in the orchestrator registry is currently processing."""
        with self._lock:
            return any(job.status == JobStatus.PROCESSING for job in self.jobs.values())

    def get_jobs_snapshot(self) -> List[Dict[str, Any]]:
        """Return an in-memory snapshot of all active documents in frontend DocumentItem format."""
        with self._lock:
            status_map = {
                JobStatus.UPLOADED: "Not extracted",
                JobStatus.QUEUED: "Waiting",
                JobStatus.PROCESSING: "Processing",
                JobStatus.SUCCESS: "Done",
                JobStatus.FAILED: "Failed",
                JobStatus.CANCELLED: "Waiting",
            }
            snapshot: List[Dict[str, Any]] = []

            for job in self.jobs.values():
                sorted_page_items = sorted(job.pages_data.items(), key=lambda kv: kv[0])
                full_text = (
                    "\n\n---\n\n".join(p.get("text", "") for _, p in sorted_page_items)
                    if sorted_page_items
                    else ""
                )

                doc_status = status_map.get(job.status, "Waiting")
                if job.status == JobStatus.SUCCESS and any(
                    p.get("truncated", False) for p in job.pages_data.values()
                ):
                    doc_status = "Truncated"

                if job.status == JobStatus.UPLOADED:
                    status_note = "Ready to extract"
                elif job.status == JobStatus.CANCELLED:
                    status_note = "Job cancelled"
                else:
                    status_note = job.error

                pages_data: Dict[int, Dict[str, Any]] = {}
                for p_num, p in sorted_page_items:
                    pages_data[p_num] = {
                        "pageNumber": p_num,
                        "text": p.get("text", ""),
                        "latency": p.get("latency", 0.0),
                        "tokens": p.get("tokens", 0),
                        "isTruncated": p.get("truncated", False),
                    }

                file_size_str = "0.0 MB"
                if job.file_path and job.file_path.exists():
                    try:
                        size_bytes = job.file_path.stat().st_size
                        if size_bytes >= 1024 * 1024:
                            file_size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                        else:
                            file_size_str = f"{size_bytes / 1024:.1f} KB"
                    except OSError:
                        file_size_str = "0.0 MB"

                processed_pages = (
                    job.current_page
                    if job.status == JobStatus.PROCESSING
                    else len(job.pages_data)
                )

                snapshot.append(
                    {
                        "id": job.job_id,
                        "name": job.filename,
                        "pages": job.page_count,
                        "processedPages": processed_pages,
                        "size": file_size_str,
                        "status": doc_status,
                        "statusNote": status_note,
                        "currentPage": 1,
                        "docType": "custom-image",
                        "previewImageUrl": f"/api/documents/{job.job_id}/pages/1/preview",
                        "extractedText": full_text,
                        "pagesData": pages_data,
                        "run_id": job.run_id,
                        "runId": job.run_id,
                        "promptMode": job.prompt_mode,
                    }
                )

            return snapshot

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

    def enqueue(self, job_id: str, prompt_mode: str = "text") -> None:
        """Enqueue an existing job for processing."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(f"Job '{job_id}' not found")
            job.prompt_mode = prompt_mode
            job.run_id = uuid.uuid4().hex[:8]
            job.pages_data.clear()
            job.current_page = 0
            job.cancel_event = threading.Event()
            job.error = None
            job.result = None
            job.status = JobStatus.QUEUED
        self._queue.put(job_id)

    def cancel(self, job_id: str) -> bool:
        """Signal cooperative cancellation for a job."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            job.cancel_event.set()
            if job.status in (JobStatus.QUEUED, JobStatus.UPLOADED):
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
                    "run_id": job.run_id,
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

            doc_settings = getattr(self.engine, "settings", None)
            if doc_settings is not None:
                doc_settings = copy.deepcopy(doc_settings)
                cfg = JobConfig(
                    dpi=getattr(doc_settings, "dpi", 100),
                    max_image_dimension=getattr(doc_settings, "max_image_dimension", 2048),
                    prompt_mode=job.prompt_mode,
                )
            else:
                cfg = JobConfig(prompt_mode=job.prompt_mode)

            logger.info(
                "Executing job %s with prompt_mode '%s' (effective prompt: %r)",
                job.job_id,
                job.prompt_mode,
                cfg.effective_prompt,
            )

            try:
                result = self.engine.process_document(
                    source=job.file_path,
                    config=cfg,
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
