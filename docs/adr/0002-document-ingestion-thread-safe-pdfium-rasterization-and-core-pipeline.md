# ADR-0002: Document Ingestion, Thread-Safe PDFium Rasterization, and Core Pipeline

## Status
Accepted

## Date
2026-11-13

## Context
AksaraSight ingests diverse document types: multi-page PDFs, high-resolution scans, smartphone photographs, dense spreadsheet tables, and corrupted files. Processing these inputs within a concurrent desktop environment presents several reliability challenges:
1. **PDFium Thread-Safety & Reentrant Deadlocks**: PDFium (`pypdfium2`) is written in C and is not thread-safe. Unsynchronized concurrent calls trigger memory access violations and segmentation faults. Using non-reentrant locks also causes deadlocks when nested pipeline helpers or callbacks re-acquire the mutex within the same thread.
2. **Decompression Bombs & Memory Exhaustion**: Untrusted image scans or extremely high-resolution files can exhaust host RAM during decompression, causing out-of-memory crashes.
3. **Global Configuration Contamination**: In earlier designs, document rasterization resolution (`dpi`) was stored exclusively as a global setting in `Settings` (`settings.dpi`, default 100). Adjusting DPI for a single difficult scan mutated global configuration, causing race conditions and configuration pollution across multi-document queues.
4. **Interface Encapsulation Leaks**: Web and CLI presentation layers previously reached into `OCREngine` private internals (such as mutating `engine.client.endpoint` directly), violating the requirement for thin presentation interfaces.
5. **Mid-Flight Parameter Mutation**: When settings updates occurred during active extraction, shared client connection parameters (`endpoint`, `timeout`, `max_retries`) were altered mid-flight, destabilizing active requests.
6. **Artifact Output Safety**: Non-atomic file writes risk corrupted exports if interrupted, and absolute paths in JSON exports risk leaking workstation directory structures.

## Decision
1. **Reentrant Mutex Guard (`_PDFIUM_LOCK`)**:
   - Wrap all PDFium C API calls and document page probing in module-level `_PDFIUM_LOCK = threading.RLock()` in `core/pipeline.py`.
   - Encapsulate all document page count inquiries in `core.pipeline.get_page_count()` under lock, preventing web or CLI modules from importing PDFium directly.
2. **Explicit Bitmap Detachment & Memory Lifecycle**:
   - Manage `PdfBitmap` lifecycle explicitly under `_PDFIUM_LOCK`: call `bitmap.to_pil().copy()` to detach the PIL image buffer from C memory, followed by `bitmap.close()` in a `try...finally` block. This prevents Python garbage collection of `PdfBitmap` from deallocating C memory outside the mutex.
   - Release `_PDFIUM_LOCK` during subsequent Pillow downscaling and base64 encoding to maximize concurrency across threads.
3. **Decompression Bomb Guard & Image Validation**:
   - Enforce two-stage image validation: `Image.verify()` to inspect image headers, followed by reopening with `Image.load()` to catch truncated raster streams.
   - Guard against decompression bombs by validating total pixel count against `MAX_RASTER_PIXELS` (89,478,485 pixels) before rendering.
   - Standardize output to 100 DPI RGB JPEG base64 data URLs capped at a 2048px maximum dimension via Lanczos downscaling.
4. **Per-Job Dynamic Configuration Routing**:
   - Parameterize extraction at the job level. `POST /api/documents/{job_id}/extract` accepts `ExtractRequest(prompt_mode, dpi)` where `dpi` is validated (50–600) and stored in `JobState.dpi`.
   - During worker execution in `WebOrchestrator._worker_loop`, construct `JobConfig` using the per-document `dpi`, falling back to `settings.dpi` only when omitted.
5. **Encapsulated Engine Reconfiguration (`OCREngine.reconfigure`)**:
   - Provide `reconfigure(self, settings: Settings) -> None` on `core.engine.OCREngine`.
   - Update engine settings and reinitialize internal HTTP client state atomically inside the engine, keeping presentation layers as thin consumers calling `engine.reconfigure(new_settings)`.
6. **In-Flight Client Parameter Snapshotting**:
   - Snapshot client connection parameters (`endpoint`, `timeout`, `max_retries`) from `doc_settings` per call in `VisionClient.complete()`, isolating running documents from mid-flight configuration mutations.
7. **Atomic Multi-Format Artifact Generation**:
   - Stream pages via a generator pipeline (`ingest()` yielding `ExtractedPage`) to maintain low memory consumption.
   - Generate OOXML Word `.docx` documents with table fidelity (`core/docx_export.py`).
   - Format JSON outputs with sanitized relative paths (`base_dir=target_upload_dir`) and write all export files atomically via `.tmp` staging and `os.replace`.

## Alternatives Considered & Rejected
- **Poppler / `pdf2image`**: Rejected because Poppler requires external binary installations (`pdftoppm.exe`) that cannot be cleanly packaged or resolved portably on Windows.
- **`PyMuPDF` (fitz)**: Rejected due to AGPL licensing restrictions, which conflict with AksaraSight's MIT license.
- **Process-Level Isolation for PDFium**: Rejected due to high inter-process communication (IPC) memory overhead when transferring raw bitmaps across processes on Windows.
- **Per-Document Persistent Metadata in Database**: Rejected to preserve the zero-database, zero-dependency local architecture.
- **Requiring Full Settings Mutation for DPI Adjustment**: Rejected because changing DPI for one document should never silently alter defaults for subsequent documents.
- **Global Mutex Locking During Extraction**: Rejected because locking the entire engine blocks harmless non-server settings changes.

## Consequences
- Eliminates C-level memory corruption and access violations during multi-threaded document processing.
- PDFium rasterization is protected against reentrant deadlocks.
- Protects the application against out-of-memory crashes from decompression bombs and malformed image inputs.
- Users can customize extraction target and resolution on a per-document basis without polluting global settings.
- Active extractions are isolated from mid-flight configuration changes.
- Presentation layers remain thin consumers of the core engine.
- Memory consumption remains low during multi-page document processing via generator streaming.
- Multi-page PDF rasterization is serialized through `_PDFIUM_LOCK` (downscaling and HTTP vision calls run concurrently).
