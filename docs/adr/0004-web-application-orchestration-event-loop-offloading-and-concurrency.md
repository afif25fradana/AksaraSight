# ADR-0004: Web Application Orchestration, Event Loop Offloading, and Concurrency

## Status
Accepted

## Date
2026-11-19

## Context
AksaraSight's Web UI workspace runs a local FastAPI and Uvicorn server on loopback. The server coordinates both asynchronous HTTP/SSE requests and CPU/disk-intensive operations:
1. **Event Loop Starvation**: Operations such as server health probing (`verify_backend`), status polling, hardware detection, PDF rasterization, Word (.docx) export, artifact directory scanning, and `ServerManager.start()`/`stop()` are inherently synchronous or blocking. Executing these blocking calls directly inside `async def` endpoints starves the single-threaded asyncio event loop, causing UI freezes, SSE stream stuttering, and health check timeouts.
2. **Queue and Cancellation Race Conditions**: In `web/orchestrator.py`, queuing originally tracked jobs solely by string `job_id`. When a job was cancelled and re-enqueued, a stale queue entry or an in-flight worker thread could wake up, overwrite `job.cancel_event`, and allow dying page completions from the cancelled run to pollute the newly active run's `pages_data` and `current_page`.
3. **Downloader Fail-Closed State Lifecycle**: In `core/model_manager.py`, `_execute_download()` lacked top-level exception handling covering filesystem directory creation and disk usage probing. An unexpected `OSError` left `self.is_downloading = True` permanently, blocking `/api/model/download` with HTTP 409 deadlocks.
4. **Memory and File Descriptor Accumulation**: Unbounded in-memory job dictionaries and lingering upload files cause memory and disk growth during extended sessions. Long-lived Server-Sent Events (SSE) connections without keepalives risk silent client disconnections and orphaned queues.
5. **Server Ownership State Drift**: `app.state.server_managed` was not cleared when a managed `llama-server` process crashed or was superseded by an external instance. Additionally, backend lifecycle transitions failed to invalidate `OCREngine`'s cached verification state.
6. **Cancellation & Deletion Filesystem Contention**: When a user cancels, deletes, or evicts a document job while the background worker thread is actively executing `OCREngine.process_document()`, immediate filesystem unlinking (`job.file_path.unlink()`) risks `PermissionError` (especially under Windows due to open file handles) and crashes the worker loop mid-pipeline.

## Decision
1. **Complete Event Loop Offloading**:
   - Offload all synchronous, CPU-intensive, or blocking disk I/O operations (`/health`, `/api/server/status`, `/api/runtime/status`, `/preview`, `/export`, `/api/output`, and server start/stop) from `async def` route handlers to worker threads via `await asyncio.to_thread(...)`.
   - Maintain state mutations (e.g., `app.state.server_managed = ...`) and request validations on the main coroutine thread, preserving thread-safety while keeping the event loop responsive.
2. **Run-Token Queue Tracking & Page Isolation**:
   - Enqueue jobs as `QueueToken = Tuple[str, str, threading.Event]` containing `(job_id, run_id, cancel_event)`.
   - Permit `enqueue()` during `PROCESSING` if `job.cancel_event` is set, assigning a fresh `run_id` and unset `cancel_event`.
   - Guard `on_progress` updates with `if (item_run_id is not None and job.run_id != item_run_id) or (item_cancel_event is not None and item_cancel_event.is_set()) or job.cancel_event.is_set(): return`, preventing in-flight pages from cancelled runs from polluting subsequent runs.
   - Guard `_worker_loop` to cleanly handle stop sentinels (`""`) and raw string insertions without `ValueError`.
   - Introduce a dedicated cancellation lock (`threading.Lock`) in `WebOrchestrator` to guard cancellation requests and status mutations atomically.
3. **Single-Worker FIFO GPU Queue**:
   - Enforce sequential document execution via a single worker thread, preventing GPU compute and VRAM contention.
   - Broadcast the `queued` SSE event immediately upon document registration.
4. **Memory & Resource Governance**:
   - Enforce a retention limit (`MAX_STORED_JOBS = 50`) in `WebOrchestrator`. Automatically evict the oldest terminal jobs (`SUCCESS`, `FAILED`, `CANCELLED`) and delete their temporary uploaded files when registering or completing jobs.
   - Bound SSE subscriber queues (`asyncio.Queue(maxsize=100)`) and emit periodic 15-second keepalive pings (`comment="ping"`) to detect client disconnects and prune subscriber queues within 15 seconds.
   - Configure `requests.Session` in `ServerManager` with `HTTPAdapter(pool_connections=10, pool_maxsize=10)` to eliminate socket exhaustion and connection thrashing during high-frequency polling.
5. **Top-Level Fail-Closed Downloader Execution**:
   - Enclose the entire body of `ModelDownloader._execute_download()` in a `try...except Exception as exc: ... finally: self.is_downloading = False` block, guaranteeing that any filesystem or network failure resets the downloading flag under all conditions.
6. **Synchronized Server Ownership & Lifecycle Invalidation**:
   - Synchronize `app.state.server_managed = False` whenever `poll_status().ownership != ServerOwnership.MANAGED`.
   - Wire `server_manager.on_lifecycle_change = app_engine.invalidate_backend_verification`.
7. **Worker Thread Execution Tracking & Deferred Unlinking**:
   - Track worker execution status atomically with `self._is_worker_executing: bool` and `self._current_job_id: Optional[str]` inside the orchestrator mutex (`self._lock`).
   - Expose thread-safe queries `is_busy()` (`self._is_worker_executing or not self._queue.empty()`) and `is_processing()` (`self._is_worker_executing or any(job.status == JobStatus.PROCESSING for job in self.jobs.values())`) to enable lifecycle supervisors (`SSEShutdownSupervisor`) and API handlers to inspect orchestrator activity without inspecting private queue queues.
   - Implement deferred file unlinking (`defer_or_unlink(file_path, job_id)`): if a file is targeted for deletion while its associated job is actively executing on the worker thread (`self._is_worker_executing and (job_id is None or job_id == self._current_job_id)`), defer unlinking by appending the path to `self._pending_unlinks`.
   - In `_worker_loop()`, execute `process_document()` within a `try...finally` block that guarantees resetting `_is_worker_executing = False` and drains all `_pending_unlinks` after the worker thread releases file handles, preventing file-in-use exceptions on Windows.

## Alternatives Considered & Rejected
- **External Process Task Queue (Celery / Redis / RQ)**: Rejected due to heavy dependency overhead, external service requirements, and unnecessary complexity for a local single-user desktop application.
- **Rewriting Core Engine to Asyncio**: Rejected because the core pipeline (`core/pipeline.py`) is shared with the synchronous CLI (`cli/main.py`). Maintaining dual sync/async APIs or forcing async on the CLI adds code complexity without benefit.
- **Multiple Concurrent Inferences (Parallel Worker Threads)**: Rejected because multimodal vision LLMs (`GLM-OCR` / `PaddleOCR-VL`) saturate GPU VRAM and compute. A strict single-worker FIFO queue prevents out-of-memory (OOM) crashes on local consumer GPUs.
- **FastAPI Synchronous `def` Handlers for Server Start/Stop**: Rejected because converting handlers to synchronous `def` runs the entire route in Starlette's threadpool, breaking consistency with the async architecture in `web/app.py`.
- **Immediate Unlink on Job Cancellation / Pruning**: Rejected because unlinking a file while `pypdfium2` or OCR workers hold open file descriptors raises `PermissionError` on Windows, terminating the worker loop.
- **Thread Interruption / Hard Process Killing**: Rejected because abruptly killing worker threads leaves backend inference models in inconsistent states, leaks GPU memory, and corrupts open file handles.
- **Unbounded Job History**: Rejected because retaining raw images, preview bitmaps, and results in memory causes memory bloat on large multi-page PDF workloads.

## Consequences
- The Web UI remains fully responsive during long-running OCR extractions, document rasterization, server startup/shutdown, and artifact scanning.
- Queue races and in-flight cancellation state corruption are eliminated across Web API and worker threads.
- Memory and temporary file storage remain bounded over extended application uptime (`MAX_STORED_JOBS = 50`).
- Client browser closures and network resets are detected within 15 seconds, preventing memory leaks in the SSE broadcaster.
- Model and runtime downloader states fail closed under all error conditions, eliminating permanent 409 deadlocks.
- Job cancellation, deletion, and terminal job pruning occur cleanly without Windows `PermissionError` file-locking collisions while worker threads are active.
- Server lifecycle supervision can reliably query `orchestrator.is_busy()` to evacuate active jobs before shutting down the server.
- The shared core engine remains synchronous, testable, and scriptable from the CLI.
- Jobs execute sequentially in FIFO order (one document at a time).
