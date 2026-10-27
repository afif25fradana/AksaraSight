# ADR-0010: Core Engine Encapsulation, Runtime Path Decoupling, and Concurrency Hardening

## Status
Accepted

## Date
2026-10-23

## Context
1. **Engine Interface Leaks & Route Monkey-Patching**: In `web/app.py`, settings updates via `PATCH /api/settings` directly mutated `app.state.engine.settings = new_settings` and reached into the engine's private client (`app.state.engine.client.endpoint = ...`, `app.state.engine.client.model = ...`). This violated the core architectural invariant of "Thin Interfaces", which requires interfaces to route through `OCREngine` without mutating engine internals directly.
2. **Circular Import & Configuration Coupling**: `config/settings.py` attempted to resolve dynamic runtime binary paths by importing `core.runtime_manager`. This coupled the static configuration layer to runtime execution mechanics and created circular dependency hazards.
3. **Reentrant Deadlock Hazard in PDF Pipeline**: In `core/pipeline.py`, PDFium rasterization was guarded by a non-reentrant `threading.Lock()`. When nested helpers or callbacks acquired the lock within the same thread execution flow, deadlocks were possible.
4. **Race Conditions in Batch Job Cancellation**: In `web/orchestrator.py`, job cancellation checked and updated state without atomic synchronization, allowing a race between an incoming cancel HTTP request and an in-flight worker thread transitioning from RUNNING to COMPLETED.
5. **Orphaned Subprocess OS Handles on Windows**: In `core/server_manager.py`, terminating child processes did not explicitly close standard stream pipes (`stdout`, `stderr`) or reset job handles, leaving lingering file descriptors and kernel handles.
6. **DLL Hijacking Attack Surface in Hardware Probe**: In `core/hardware.py`, `ctypes.util.find_library("nvcuda")` or unanchored `ctypes.WinDLL("nvcuda.dll")` searched the current working directory and system PATH, presenting a DLL search-order preloading vulnerability.
7. **Event Loop Blockage during Artifact Directory Scanning**: In `web/app.py`, `GET /api/jobs/{job_id}/artifacts` performed synchronous filesystem traversal (`os.listdir`) and stat checks directly on the asyncio event loop, causing latency spikes when scanning large directories or network-attached storage.
8. **Permissive Mocks and Signature Drift in Test Suite**: In `tests/test_cli.py`, `unittest.mock.patch("cli.main.OCREngine")` without `autospec=True` allowed test assertions to pass even if method names or argument signatures drifted from `OCREngine`'s actual signature.

## Decision
1. **Encapsulated Engine Reconfiguration (`OCREngine.reconfigure`)**:
   - Provide `reconfigure(self, settings: Settings) -> None` on `core.engine.OCREngine`.
   - Update engine settings and reinitialize internal HTTP client state atomically inside the engine, keeping `web/app.py` as a thin consumer calling `app.state.engine.reconfigure(new_settings)`.
2. **Runtime Path Decoupling via `resolve_effective_server_path`**:
   - Keep `config/settings.py` strictly focused on environment variables and frozen configuration data.
   - Relocate dynamic discovery of the managed `llama-server` binary to `core.runtime_manager.resolve_effective_server_path(settings: Settings) -> Path`.
3. **Reentrant Locking with `threading.RLock`**:
   - Replace `threading.Lock` with `threading.RLock()` for `_PDFIUM_LOCK` in `core/pipeline.py` to support reentrant locking within rasterization pipelines.
4. **Atomic Job Cancellation Synchronization**:
   - Introduce a dedicated cancellation lock (`threading.Lock`) in `WebOrchestrator` to guard cancellation requests and status mutations atomically.
5. **Explicit Subprocess Stream and Handle Cleanup**:
   - In `ServerManager.stop()`, explicitly close `proc.stdout` and `proc.stderr` and clean up Windows Job Object handles to guarantee zero OS handle leaks.
6. **CUDA DLL Pinning to System32**:
   - Pin NVIDIA CUDA driver DLL loading on Windows strictly to `os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvcuda.dll")`, eliminating DLL search-order preloading hazards.
7. **Asynchronous Disk I/O Offloading for Artifact Scans**:
   - Wrap artifact directory enumeration in `web/app.py` with `await asyncio.to_thread(_scan_output_artifacts, out_dir)`, preventing event loop stalls.
8. **Autospec Mock Enforcement**:
   - Enforce `autospec=True` across `OCREngine` mocks in `tests/test_cli.py` to prevent mock interface drift.

## Alternatives Considered & Rejected
- **Full Async Rewrite of Engine Pipeline**: Rejected because CPU/GPU-bound rasterization and OCR requests run naturally in thread pools (`ThreadPoolExecutor`). Offloading at interface boundaries via `asyncio.to_thread` provides optimal performance without speculative architectural rewrites.
- **Dynamic PATH Prepending for CUDA DLLs**: Rejected because modifying PATH or trusting CWD exposes the app to untrusted DLL injection; system driver DLLs reliably reside in `%SystemRoot%\System32`.
- **Separate Mock Specification Classes**: Rejected because `unittest.mock.patch(..., autospec=True)` natively introspects `OCREngine` with zero maintenance overhead.

## Consequences
- `web/app.py` and `cli/main.py` strictly adhere to the Thin Interface architectural invariant.
- Eliminated circular dependency hazard between `config` and `core`.
- PDFium rasterization is protected against reentrant deadlocks.
- Subprocess handles and stream pipes are cleanly released upon process exit.
- CUDA probing is secure against local DLL search-order hijacking.
- CLI unit tests strictly enforce `OCREngine` interface contracts.
