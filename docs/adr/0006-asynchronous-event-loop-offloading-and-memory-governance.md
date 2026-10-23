# ADR-0006: Asynchronous Event Loop Offloading and Memory Governance

## Status
Accepted

## Date
2026-10-18

## Context
AksaraSight's Web UI workspace runs a local FastAPI and Uvicorn server on loopback. The server handles both asynchronous HTTP/SSE requests and CPU/disk-intensive operations:
1. Server health probing (`verify_backend`), status polling, hardware detection, PDF rasterization, and Word (.docx) document generation are inherently synchronous or blocking.
2. Executing blocking calls directly inside `async def` endpoints starves the single-threaded asyncio event loop, causing UI freezes, SSE stream stuttering, and health check timeouts.
3. Unbounded in-memory job dictionaries and lingering upload files cause memory and disk growth during extended user sessions.
4. Long-lived Server-Sent Events (SSE) connections without keepalives risk silent client disconnections and orphaned queues.

## Decision
1. **Event Loop Offloading**: Offload all synchronous, CPU-intensive, or blocking disk I/O operations from `async def` route handlers (`/health`, `/api/server/status`, `/api/runtime/status`, `/preview`, `/export`) to worker threads via `await asyncio.to_thread(...)`.
2. **Bounded In-Memory Job Retention**: Enforce a strict retention limit (`MAX_STORED_JOBS = 50`) in `WebOrchestrator`. Automatically evict the oldest terminal jobs (`SUCCESS`, `FAILED`, `CANCELLED`) and delete their temporary uploaded files when registering or completing jobs.
3. **SSE Supervision & Keepalives**: Bound SSE subscriber queues (`asyncio.Queue(maxsize=100)`) and emit periodic 15-second keepalive pings (`comment="ping"`) to detect client disconnects and clean up subscriber queues.
4. **HTTP Connection Pooling**: Configure `requests.Session` in `ServerManager` with `HTTPAdapter(pool_connections=10, pool_maxsize=10)` to eliminate socket exhaustion and connection thrashing during high-frequency polling.

## Alternatives Considered & Rejected
- **External Process Task Queue (Celery / Redis / RQ)**: Rejected due to heavy dependency overhead, external service requirements, and unnecessary complexity for a local single-user desktop application.
- **Rewriting Core Engine to Asyncio**: Rejected because the core pipeline (`core/pipeline.py`) is shared with the synchronous CLI (`cli/main.py`). Maintaining dual sync/async APIs or forcing async on the CLI adds code complexity without benefit.
- **Unbounded Job History**: Rejected because retaining raw images, preview bitmaps, and results in memory causes memory bloat on large multi-page PDF workloads.

## Consequences
- The Web UI remains fully responsive during long-running OCR extractions and document rasterization.
- Memory and temporary file storage remain bounded over extended application uptime.
- Client browser closures and network resets are detected within 15 seconds, preventing memory leaks in the SSE broadcaster.
- The shared core engine remains purely synchronous, clean, and easily testable by CLI and scripts.
