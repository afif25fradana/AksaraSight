# ADR-0007: Per-Job Dynamic Configuration Routing and Unified Extraction Pipeline

## Status
Accepted

## Date
2026-10-18

## Context
1. AksaraSight previously stored document rasterization resolution (`dpi`) exclusively as a global setting in `Settings` (`settings.dpi`, default 100).
2. Modifying rasterization resolution for difficult scans (e.g., blurry photographs, small font legal contracts, or dense tables) required modifying global settings or persisting them to `.env`. This created cross-job configuration pollution and race conditions in multi-document queues.
3. The frontend interface presented an ambiguous "Task Mode" segmented control with vague options that did not expose resolution control or clarify the purpose of each mode to the user.
4. The user interface contained synthetic UI state mutations (such as local fake server state toggles, optimistic queue stubs, and synthetic file exports) rather than directly driving backend FIFO task execution.

## Decision
1. **Dynamic Per-Job Extraction Parameters**: Parameterize document extraction at the job level. `POST /api/documents/{job_id}/extract` accepts `ExtractRequest(prompt_mode, dpi)` where `dpi` is validated (50–600) and stored in `JobState.dpi`.
2. **Dynamic JobConfig Construction**: During worker execution in `WebOrchestrator._worker_loop`, construct `JobConfig` using the job's per-document `dpi` if provided, falling back to `settings.dpi` only when omitted.
3. **Unified Extraction Options Popover**: Replace the ambiguous Task Mode control with a unified options popover combining:
   - **Extraction Target**: Full Document (`text`), Single Table Crop (`table`), and Math & Formulas (`formula`).
   - **Scan Detail / Resolution**: Standard (`100 DPI`, default), High Detail (`150 DPI`), and Ultra Sharp (`200 DPI`).
4. **Resilient FIFO Background Queue & Direct Lifecycle Event Broadcasting**:
   - Allow enqueuing documents while extraction is actively running on another job.
   - Broadcast the `queued` event across Server-Sent Events (SSE) immediately upon enqueuing.
   - Wire all UI retry, enqueue, and server toggle actions directly to backend endpoints (`/api/documents/{id}/extract`, `/api/server/status`), eliminating synthetic client-side stubs.

## Alternatives Considered & Rejected
- **Per-Document Persistent Metadata in Database**: Rejected to preserve the zero-database, zero-dependency local architecture. Job state is held in memory during the session.
- **Multiple Concurrent Inferences (Parallel Worker Threads)**: Rejected because multimodal vision LLMs (`GLM-OCR`) saturate GPU VRAM and compute. A strict single-worker FIFO queue prevents out-of-memory (OOM) crashes on local consumer GPUs.
- **Requiring Full Settings Mutation for DPI Adjustment**: Rejected because changing DPI for one document should never silently alter defaults for subsequent documents.

## Consequences
- Users can customize extraction target and resolution on a per-document basis without affecting global settings.
- Documents can be enqueued freely without blocking user interaction; jobs process sequentially in FIFO order without GPU contention.
- The UI reflects the true state of the backend server and job queue with zero mock or synthetic delays.
