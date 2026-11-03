# ADR-0012: Concurrency Governance, Run-Token Queue Isolation, and Wire Contract Synchronization

## Status
Accepted

## Date
2026-11-03

## Context
1. **Queue & Cancellation Races in Web Orchestrator**: In `web/orchestrator.py`, queuing tracked jobs solely by string `job_id`. When a queued or processing job was cancelled and re-enqueued, a stale queue entry or an in-flight worker thread could wake up, overwrite `job.cancel_event`, and allow dying page completions from a cancelled run to pollute the newly active run's `pages_data` and `current_page`.
2. **Downloader Fail-Closed State Lifecycle**: In `core/model_manager.py`, `_execute_download()` lacked top-level exception handling covering directory creation and disk usage probing. An unexpected `OSError` or Windows `[WinError 32]` left `self.is_downloading = True` permanently, blocking `/api/model/download` with HTTP 409.
3. **In-Flight Client Configuration Isolation**: `PATCH /api/settings` modified the shared `Settings` dataclass while OCR jobs were in flight. While document rasterization settings were snapshotted, client network parameters (`endpoint`, `timeout`, `max_retries`) on `VisionClient` were global and mutable mid-flight.
4. **Server Ownership State Drift & Cache Invalidation**: `app.state.server_managed` was not cleared when a managed `llama-server` process crashed or was superseded by an external instance. Additionally, backend lifecycle transitions failed to invalidate `OCREngine`'s cached verification state.
5. **Security & Output Hygiene**: In `web/app.py`, `export_document` (`format=json`) relativized source paths against `out_dir` rather than `target_upload_dir`, leaking upload parent directories in JSON responses. Artifact exports wrote directly to disk without atomic `.tmp` replacement. `DELETE /api/output/{filename}` lacked extension validation and symlink checks.
6. **Advisory File Lock Contention on Windows NTFS**: `lifespan` shutdown unlinked `.instance.lock`, causing `[WinError 32]` access-denied contention and re-acquisition races during rapid application restart on Windows.
7. **Logging Hierarchy & Diagnostic Field Truncation**: In `web/__main__.py`, setting `root_logger.setLevel(logging.INFO)` caused internal `DEBUG` logs from `web` and `core` to be discarded before reaching the rotating file handler. In `web/app.py`, `post_doctor` evaluated `getattr(c, "details", getattr(c, "message", None))`, which returned `None` because `DiagnosticCheck.details` defaulted to `None`, dropping the message text and breaking hardware display in the Web UI.
8. **Test Suite Mock Drift & Test Cheating**: In `tests/web_fixtures.py`, `MockEngine.process_document` raised `ServerOfflineError` directly rather than returning an aborted `OCRResult` (diverging from `OCREngine` invariants), and `MockModelDownloader.download()` never reset `is_downloading = False`. In `tests/test_web_documents.py`, `test_reextraction_resets_run_id_and_progress` manually forced `job.status = JobStatus.CANCELLED` to bypass orchestrator re-enqueue guards.

## Decision
1. **Run-Token Queue Tracking & Page Isolation**:
   - Enqueue jobs as `QueueToken = Tuple[str, str, threading.Event]` containing `(job_id, run_id, cancel_event)`.
   - Permit `enqueue()` during `PROCESSING` if `job.cancel_event` is set, assigning a fresh `run_id` and unset `cancel_event`.
   - Guard `on_progress` updates with `if (item_run_id is not None and job.run_id != item_run_id) or (item_cancel_event is not None and item_cancel_event.is_set()) or job.cancel_event.is_set(): return` to prevent dying in-flight pages from polluting subsequent runs.
   - Guard `_worker_loop` to cleanly handle `stop()` sentinels (`""`) and raw string insertions without `ValueError`.
2. **Top-Level Fail-Closed Downloader Execution**:
   - Enclose the entire body of `ModelDownloader._execute_download()` in a `try...except Exception as exc: ... finally: self.is_downloading = False` block, guaranteeing that any filesystem or network failure resets the downloading flag.
3. **In-Flight Client Parameter Snapshotting & Scoped Settings Guard**:
   - Add optional `endpoint`, `timeout`, and `max_retries` kwargs to `VisionClient.complete()`. Snapshot these parameters from `doc_settings` in `OCREngine.process_document()` and pass them per-call, with backward-compatible fallback for legacy client signatures.
   - Scope the 409 guard in `PATCH /api/settings` strictly to `server_keys` (`backend`, `runtime_mode`, `managed_backend_override`, `llama_server_path`, `model_repo`, `local_endpoint`) while extraction is active. Non-server settings (`dpi`, `timeout`, `max_tokens`) return HTTP 200 immediately.
4. **Synchronized Server Ownership & Lifecycle Invalidation**:
   - Synchronize `app.state.server_managed = False` whenever `poll_status().ownership != ServerOwnership.MANAGED`.
   - Wire `server_manager.on_lifecycle_change = app_engine.invalidate_backend_verification`.
5. **Output Path Sanitization, Atomic Writes & Deletion Guards**:
   - Pass `base_dir=target_upload_dir` to `format_output` in `export_document` to prevent username and parent directory leaks in JSON exports.
   - Write export files atomically via `.tmp` scratch files and `os.replace`.
   - Require `target.suffix.lower() in ALLOWED_OUTPUT_EXTS`, reject symlinks, and assert canonical directory containment in `delete_output_file`.
6. **Advisory Lock Retention on Lifespan Exit**:
   - Retain the 0-byte `.instance.lock` file on disk upon application shutdown, releasing only the OS kernel lock via `_release_instance_lock`.
7. **Scoped DEBUG Logging & Diagnostic Schema Alignment**:
   - Configure loggers `"web"` and `"core"` at `logging.DEBUG` while maintaining `root_logger` at `logging.INFO`.
   - Update `post_doctor` to use `details = c.details if getattr(c, "details", None) is not None else getattr(c, "message", None)` and include `"remediations": getattr(report, "remediations", [])`.
   - Add `category="Hardware"`, `title="Acceleration / Hardware"`, and `details=...` to hardware diagnostic checks.
8. **Anti-Mock Drift & Test Suite Cleansing**:
   - Update `MockEngine.process_document` to return an aborted `OCRResult` on offline failure, matching `OCREngine`.
   - Update `MockModelDownloader.download()` to reset `is_downloading = False` and return `False` on cancellation.
   - Remove manual status mutation cheating, eliminate redundant duplicate tests, and remove alias test assignments.

## Consequences
- Queue races and in-flight cancellation state corruption are eliminated across Web API and worker threads.
- In-flight document extraction is safely isolated from mid-flight settings mutations without globally locking non-server updates.
- Advisory file locking operates cleanly across Windows and POSIX without NTFS file-locking contention.
- Model and runtime downloader states fail closed under all error conditions, eliminating permanent 409 deadlocks.
- The test suite strictly mirrors production engine and downloader contracts with zero artificial state mutations.
