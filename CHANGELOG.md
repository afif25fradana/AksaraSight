# Changelog & Project Evolution

A chronological overview of the development, architecture, security hardening, and audit milestones for **AksaraSight**.

---

## Current State: v1.0.0 (Feature-Complete for Current Scope)
- **370 automated tests passing** (100% pass rate across unit, functional, integration, and smoke tests).
- **All 5 implementation phases complete** (Core, CLI, Desktop GUI Studio, Live Backend Integration, Server Supervision).
- **All 7 comprehensive audit categories formally closed** (Security x2, Performance, Code Quality/Ponytail, Correctness/Data Integrity, Test Coverage Gaps, UX/Accessibility, plus Managed Runtime Supply-Chain Security Review).
- **Serving Configuration & Multimodal Self-Test Hardening complete** (Empirically verified b10930 arguments, 1x1 multimodal probe, session caching, and local GGUF mmproj safeguards).

---

## Milestones

### Security Hardening Pass (Loopback Host Binding, Proxy Defense, JSON Path & Error Sanitization)
*Focus: Defense-in-depth isolation, loopback binding enforcement, proxy interception prevention, and path sanitization in JSON exports.*
- **Explicit Loopback Host Binding**: Added explicit `"--host", "127.0.0.1"` to `llama-server` subprocess launch in `core/server_manager.py`, eliminating reliance on upstream binary default host behavior.
- **Proxy Interception Defense**: Set `trust_env = False` on `requests.Session` instances in `core/client.py` and `core/server_manager.py`, guaranteeing OS-level proxy environment variables (`HTTP_PROXY`/`HTTPS_PROXY`) cannot intercept local loopback inference traffic.
- **JSON Export Path & Error Sanitization**: Added `sanitize_export_error()` to `core/formatter.py` to redact absolute local filesystem paths embedded within error messages (`data["error"]` and `page["error"]`) when `sanitize_path=True`. Ensured single-file CLI JSON output routes through `format_output()`.
- **Result:** **370 / 370 tests passing**.

---

### CLI Diagnostic Health-Check (`--doctor`)
*Focus: Operational self-diagnostics, hardware capability reporting, runtime validation, and end-to-end vision probing.*
- **Standalone Diagnostic Flag**: Added `--doctor` flag to `AksaraSight-CLI` (`AksaraSight-CLI.exe` / `python -m cli.main`).
- **5-Stage Comprehensive Health Check**: Evaluates configuration sanity, hardware/GPU detection (`detect_hardware()`), runtime installation status (managed build vs custom binary), server reachability (`probe_server_health()`), and end-to-end multimodal inference (`OCREngine.verify_backend()` with 1x1 test image probe).
- **Executable Rebrand**: Renamed CLI target to `AksaraSight-CLI.exe` in `build_portable.spec` and `scripts/build_portable.py` for branding consistency.
- **Result:** **367 / 367 tests passing** (+6 new unit tests in `tests/test_cli.py`).

---

### Serving Configuration & Multimodal Self-Test Hardening
*Focus: Verified serving arguments, 1x1 multimodal probe, session caching, and local-GGUF mmproj safeguard.*
- **Multimodal Startup Probe**: Added `VisionClient.verify_multimodal_support()` using a 1x1 test PNG to detect text-only servers (e.g. missing `mmproj`) before document processing.
- **Session Caching & Lifecycle Invalidation**: Cached probe result in `OCREngine._multimodal_verified`; wired invalidation to `ServerManager.start()`/`stop()`, external server adoption, settings changes, and server status transitions.
- **Local GGUF mmproj Safeguard**: Added auto-detection for adjacent `*mmproj*.gguf` files in `core/server_manager.py` with an explicit warning if missing.
- **CLI & GUI Wiring**: Wired `verify_backend()` to run once prior to batch processing in CLI and before first job in GUI session.
- **Documentation Refinements**: Softened absolute claims in `README.md`, clarified SHA-256 digest scope for Managed Runtime binaries vs model weights, and documented explicit manual server commands.
- **Result:** **361 / 361 tests passing**.

---

### Audit Round 7: UX & Accessibility Audit
*Focus: First-run clarity, keyboard accessibility, preview accuracy, and visual polish.*
- **Friendly Error Messages**: Added `_friendly_err()` in the GUI to translate raw OS exceptions (`WinError 2`, `ConnectionError`) into human-readable footer notices while preserving full stack traces in diagnostic logs.
- **Keyboard Navigation**: Bound `<Escape>` to cleanly dismiss `SettingsWindow` and `SecurityConfirmationDialog`.
- **Processed DPI Tracking**: Added `QueueItem.processed_dpi` to record exact render resolution; displays a dynamic staleness warning (`⚠ processed @... DPI`) if global settings are changed after processing.
- **Indeterminate Progress Lifecycle**: Animated progress bar pulses in indeterminate mode during initial page rasterization before switching smoothly to determinate per-page fractions.
- **Preview Disclaimer**: Added explanatory note clarifying the difference between styled Text Preview and exact Raw Markdown.
- **A11y Verification**: Re-verified WCAG 2.1 AA contrast compliance across all 22 Calm Trust palette color pairs.
- **Result:** **345 / 345 tests passing**.

---

### Audit Round 6: Test Coverage & Robustness Hardening
*Focus: Unmocked subprocess execution, end-to-end integration, and boundary testing.*
- **PDF Downscaling Guard**: Enforced `max_image_dimension` downscaling on rendered PDF rasters in `_process_pdf()`, ensuring multi-megapixel blueprint PDFs cannot bypass memory limits.
- **Subprocess Smoke Tests**: Added automated tests verifying isolated package launches: `python -m gui -h`, `python -m cli.main --help`, and `scripts/smoke_test_gui.py`.
- **Real Loopback Integration**: Added live TCP socket integration test verifying `ServerManager` health probing against an active server.
- **Atomic Persistence Edge Cases**: Added fault-injection tests validating `.tmp` file cleanup on disk write failures.
- **Result:** **338 / 338 tests passing**.

---

### Correctness & Data Integrity Audit
*Focus: Elimination of silent failures, boundary state preservation, and disk atomicity.*
- **Null-Content Handling (Finding C-2)**: Refactored `_parse_response()` in `core/client.py` so null model messages raise `ResponseParsingError` rather than silently emitting blank successful pages.
- **Boundary-Staged Settings (Findings C-1 & C-5)**: Settings changed mid-document in Preferences are safely queued and only applied at clean document boundaries; unified CLI/GUI `JobConfig` parity.
- **Atomic File Exports (Finding C-6)**: Artifact exports write to `.md.tmp` and `.json.tmp` before performing atomic `Path.replace()`, preventing corrupt or partial files on interrupted writes.
- **Zero-Page Guard (Finding C-4)**: Empty document results explicitly resolve to `JobStatus.FAILED`.
- **Result:** **330 / 330 tests passing**.

---

### GUI Design Refinement & Theme Architecture
*Focus: Elimination of rendering artifacts and clean module DAG.*
- **Token Decoupling**: Extracted all Calm Trust color tokens into independent `gui/theme.py`, eliminating a circular import when invoking `python -m gui.app`.
- **Segmented Control Polish**: Removed default Tkinter grey borders (`border_width=0`) and aligned canvas background colors (`align_segmented_button_corners()`), eliminating 1px outer corner clipping on high-DPI Windows displays.
- **Result:** **326 / 326 tests passing**.

---

### Managed Runtime Feature (Stages 1–4 & Security Review)
*Focus: Zero-setup local inference without requiring manual llama.cpp installation.*
- **Stage 1 (Hardware Detection)**: Implemented `core/hardware.py` with zero-dependency NVIDIA GPU detection (`nvidia-smi` + `nvcuda.dll` ctypes probe with strict CUDA 12.4+ driver checks) and Vulkan discrete GPU detection (`vulkan-1.dll`). Added `--detect-hardware` CLI flag. (290 tests passing).
- **Stage 2 (Verified Downloader)**: Implemented `core/runtime_manager.py` downloading pinned release build `b10930`. Added streaming download to `.part` files, strict SHA-256 digest validation against pinned known hashes, Zip-Slip path traversal protection, staging directories, and atomic installation to `%LOCALAPPDATA%\AksaraSight\runtimes\`. (306 tests passing).
- **Stage 3 (GUI Supervision Integration)**: Added *Runtime Source* segmented control (`Managed (Auto)` vs `Custom Path`), live status badges, download progress bar, force-reinstall capability, and interactive hardware refresh. (320 tests passing).
- **Stage 4 (Supply-Chain Security Review)**: Enforced explicit subprocess CWD isolation to prevent DLL search hijacking on Windows, prioritized `System32` for `nvidia-smi`, enforced fail-closed pinned hash verification, and added post-install `.zip` cleanup. (322 tests passing).
- **Result:** **322 / 322 tests passing**.

---

### Ponytail Code Quality Audit
*Focus: Elimination of speculative abstractions, dead code, and over-engineering.*
- **Batch 1 (16 Safe Simplifications)**: Deduplicated single- vs multi-frame image loading, consolidated Calm Trust theme palettes, standardized on JPEG base64 encoding, removed pass-through wrapper methods and obsolete method aliases, inlined unique stem resolution, and pruned unused imports. (286 tests passing).
- **Batch 2 (4 Architecture Prunes)**: Removed unused in-memory bytes/buffer ingestion paths across pipeline and engine (enforcing clean filesystem paths), pruned base64 image retention plumbing from memory in favor of on-demand rasterization, and established canonical `OCR_*` environment variable precedence with deprecation logging for legacy names.
- **Result:** **279 / 279 tests passing**.

---

### Performance Optimization Audit
*Focus: Memory bounding, responsive GUI threading, and lazy rendering.*
- **Batch 1 (Pipeline & Ingestion)**: Wired runtime DPI end-to-end, introduced configurable `max_image_dimension: int = 2048` cap with Lanczos downscaling (reducing VRAM by 60% with 100% text match), replaced unbounded CLI batch memory accumulation with streaming booleans, and deduplicated Markdown serialization. (279 tests passing).
- **Batch 2 (GUI Memory & Rendering)**: Refactored preview pane to lazily render only the active tab on-demand, implemented on-demand disk rasterization for image previews (`retain_images=False`), and cached formatted file sizes. (283 tests passing).
- **Batch 3 (Responsiveness & Polling)**: Implemented adaptive polling backoff (50ms → 250ms for worker queue; 2s → 10s for server health), background daemon thread discovery for dropped folders, 25-item chunked UI insertion, background export thread with concurrency locking, and cross-thread Tkinter condition-lock routing via `_ui_callback_queue`.
- **Result:** **287 / 287 tests passing**.

---

### Security Hardening Audit Round 2
*Focus: OS process isolation, race conditions, and configuration persistence.*
- **Win32 Job Object (SEC-4.1)**: Bound managed `llama-server.exe` subprocesses to a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`, guaranteeing immediate process termination even upon hard application crashes.
- **Settings Propagation (SEC-3.1)**: Fixed client endpoint synchronization and implemented safe inter-document boundary settings staging.
- **Safe .env Round-Tripping (SEC-2.1)**: Single-quoted string serialization in `Settings.save_to_env()` ensuring paths with spaces, `#`, or apostrophes round-trip cleanly without backslash corruption on Windows.
- **Process Cleanup (SEC-4.2 & SEC-1.1)**: Added `atexit` hooks and active launch cancellation during server startup.
- **Result:** **251 / 251 tests passing**.

---

### Phase 5: GUI Redesign & Server Supervision
*Focus: Professional desktop studio experience and server lifecycle management.*
- **Calm Trust Theme**: Replaced generic high-contrast theme with modern Calm Trust palette (`#121417`, `#1a1d21`, `#2e6e91`), colored-dot status badges (`●`), and on-device privacy guarantee.
- **4-Tab Preview Pane**: Restructured previews into Raw Markdown, rich Text Preview, paginated Image Preview, and structured JSON Tree.
- **Real Per-Page Progress**: Wired engine progress callbacks thread-safely to a responsive progress bar.
- **Server Manager**: Implemented headless `ServerManager` with non-blocking health probing and dynamic status controls (`● READY`, `● STARTING`, `● OFFLINE`, `● ERROR`).
- **Preferences Modal**: Created `SettingsWindow` and custom dark-themed `SecurityConfirmationDialog`.
- **Result:** **241 / 241 tests passing**.

---

### Security Hardening Audit Round 1
*Focus: Attack surface reduction, loopback boundaries, and path privacy.*
- **Enforced Loopback**: Default endpoint allowlist restricted strictly to `localhost`, `127.0.0.1`, and `::1`; non-loopback addresses require explicit `--allow-remote` opt-in.
- **Sanitized Filenames**: Stripped illegal characters and sanitized legacy Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`).
- **Decompression-Bomb Defense**: Implemented `MAX_RASTER_PIXELS` (89,478,485 px) dimension preflight in PDF rasterization.
- **Cooperative Cancellation**: Added inter-page cancellation (`threading.Event`) and `--max-pages` cap.
- **Privacy Sanitization**: Automatically relativized file paths in exported `.json` artifacts against working/home directories.
- **Result:** **171 / 171 tests passing**.

---

### Phase 4: Live Backend Integration
*Focus: Empirical hardware validation and baseline establishment.*
- Verified live inference against local `llama-server` (build 10930) and `ggml-org/GLM-OCR-GGUF` on NVIDIA RTX 3050 Laptop GPU (6GB VRAM).
- Established default `-c 8192 --parallel 1` configuration, capping active VRAM to 2.18 GB (well below the 3.5 GB target).
- Standardized default rasterization at 100 DPI (~2.7s/page) to balance latency and character fidelity.
- Documented GLM-OCR model limitation with unclosed inline LaTeX math delimiters on `$DIGIT` currency amounts.

---

### Phase 3: Desktop GUI Studio
*Focus: Desktop interface implementation.*
- Implemented CustomTkinter desktop interface (`gui/app.py`) with native drag-and-drop (`tkinterdnd2`), Tcl 9 Windows path escape normalization, thread-safe background queue worker, scrollable queue manager, and artifact export actions.
- **Result:** **119 / 119 tests passing**.

---

### Phase 2: Command-Line Interface (CLI)
*Focus: Headless automation and pipeline integration.*
- Implemented scriptable CLI (`cli/main.py`) powered by `argparse`, supporting stdout streaming (`-q`), recursive batch processing (`-o`), format selection (`-f markdown|json|both`), and structured exit codes (`0`, `1`, `2`).
- **Result:** **99 / 99 tests passing**.

---

### Phase 1: Core Engine & Pipeline Foundation
*Focus: Local inference foundation.*
- Implemented `config/settings.py` (dataclass with `.env` loading and validation) and `core/models.py` (`JobStatus`, `OutputFormat`, `JobConfig`, `PageResult`, `OCRResult`).
- Implemented `core/pipeline.py` (two-stage image validation, `pypdfium2` PDF rasterization with thread locks, RGB base64 conversion).
- Implemented `core/client.py` (universal OpenAI-compatible Vision API client with persistent connection pooling and exponential jitter backoff).
- Implemented `core/engine.py` (`OCREngine` orchestrator with per-page fault isolation) and `core/formatter.py` (Markdown/JSON artifact disk exporters).
- **Result:** **86 / 86 tests passing**.
