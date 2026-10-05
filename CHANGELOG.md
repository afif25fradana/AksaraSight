# Changelog & Project Evolution

A chronological overview of the development, architecture, security hardening, and releases for **AksaraSight**.

---

## [Unreleased]

### Changed
- **Python Floor**: Raised minimum supported Python version from 3.10 to 3.12 following Python 3.10 EOL; updated CI test matrix to Python 3.12 and 3.14.

---

## Milestones

### v1.2.1 — Diagnostics & Maintenance Update (October 5, 2026)
*Focus: Runtime diagnostics, logging architecture, hardware pre-flight warnings, export collision isolation, and configuration persistence.*
- **Added**: A startup warning when a CUDA graphics card reports less than ~2.2 GB of total video memory, so likely out-of-memory problems are easier to spot. It doesn't slow down app launch.
- **Added**: When connecting to an already-running local server, AksaraSight now warns if that server is serving a different model than the one configured.
- **Added**: Desktop diagnostic logs rotate automatically (5 MB per file, up to 3 backups) and include more detail from the app itself.
- **Improved**: When starting its own local server, AksaraSight now prefers the vision projector file that matches the model's quantization.
- **Fixed**: Export file names are only checked against existing files of the same format, so other file types in the folder no longer cause unexpected numbered suffixes.
- **Fixed**: Saving settings now correctly handles values containing apostrophes.
- **Fixed**: Window minimum size and action bar layout now prevent buttons and banners from clipping when the window is resized to its minimum width.

---

### v1.2.0 — GUI Modularization, Architecture Consolidation & Test Expansion (October 1, 2026)
*Focus: Desktop GUI modularization into dedicated controllers, test suite expansion, server manager lifecycle lock hardening, and documentation sanitization. (Architectural consolidation; no breaking changes).*
- **Modular GUI Controllers (`gui/`)**: Extracted 7 dedicated, testable controller modules from `gui/app.py`:
  - `QueueManager` (`gui/queue_manager.py`): Queue item state, list selection, and batch ingestion.
  - `ExportController` (`gui/export_controller.py`): Single and batch artifact exports, cooldown state machines, and export threads.
  - `ServerUIController` (`gui/server_controller.py`): Health polling cadence, status pill visual states, and server actions.
  - `WorkerCoordinator` (`gui/worker_coordinator.py`): Background task dequeueing, boundary settings staging, and result dispatch.
  - `ImagePreviewController` (`gui/image_preview.py`): On-demand page preview rendering, pagination, and rasterization.
  - `MarkdownHighlighter` (`gui/preview_highlighter.py`): Real-time preview syntax highlighting.
  - `SecurityConfirmationDialog` (`gui/security_dialog.py`): Remote endpoint opt-in confirmation.
  - Core helper `Win32JobObject` (`core/job_object.py`): OS process containment with `KILL_ON_JOB_CLOSE`.
  - Reduced `gui/app.py` from ~2,700 lines down to 1,497 lines, with all temporary migration facades cleanly removed.
- **Test Suite Expansion**: Expanded automated test coverage across dedicated controller unit tests and build hygiene tests, achieving 100% green pass rate across Windows (Python 3.10 & 3.14) and Linux headless matrix legs.
- **Server Lifecycle Concurrency Hardening (`core/server_manager.py`)**: Introduced `_lifecycle_lock` to serialize process start/stop lifecycles across blocking process termination, freeing `_lock` to guard state snapshots without deadlock risk during concurrent stdout draining.
- **DOCX Nested List & Image Node Support (`core/docx_export.py`)**: Added recursive AST rendering for deeply nested bullet/ordered lists with depth indentation, and converted image AST nodes into clean visible placeholders.
- **CI Matrix & Dependency Pinning**: Added Python 3.10 to the GitHub Actions test matrix alongside 3.14; pinned direct dependencies across runtime, dev, and build manifests.
- **Documentation Sanitization**: Stripped internal AI process markers from codebase docstrings and synchronized technical architecture guides.

---

### v1.1.1 — Maintenance, Test-Suite Hardening & Documentation Synchronization (September 22, 2026)
*Focus: Release readiness, version alignment, batch CLI assertion hardening, and documentation synchronization. (Patch/hardening; no breaking changes).*
- **Version Alignment (`core/constants.py`)**: Bumped single-source-of-truth application version to `1.1.1` across runtime, CLI version banner, frozen executable metadata, and verification suites.
- **Batch CLI Fast-Fail Assertion (`cli/main.py`)**: Replaced unreachable dead exit code check (`if has_aborted: return 1`) following the batch execution loop with an explicit assertion (`assert not has_aborted, "unreachable: aborted batch jobs must fail fast and return early"`), ensuring aborted batch runs exit early.
- **Documentation**: Updated test counts and documentation across repository guides following recent test additions.

---

### Test Suite Improvements & Golden Fixtures (September 20, 2026)
*Focus: End-to-end integration testing, downstream mock alignment to real GLM-OCR wire responses, batch CLI fast-fail verification, and Word (.docx) export AST coverage. (Internal/test infrastructure; no user-facing behavior change).*
- **Shared Wire Fixture Helpers (`tests/fixture_helpers.py`)**: Centralized wire-accurate GLM-OCR completion response generation via `load_real_glm_ocr_response()` and `load_real_glm_ocr_error_response()`, aligning downstream mocks across `tests/test_engine.py` and `tests/test_cli.py` with real wire schema.
- **Batch CLI Functional Coverage (`tests/test_cli.py`)**: Added test coverage for multi-file progress banner reporting (`[1/3] ... -> SUCCESS`), fail-fast abort on server disconnection (guaranteeing subsequent documents are strictly never started), quiet flag banner suppression, single-file zero-page stderr reporting, missing stdout buffer error handling, and recursive directory discovery.
- **True End-to-End Loopback TCP Integration Test (`tests/test_engine.py`)**: Implemented unmocked E2E integration test exercising `pypdfium2` PDF synthesis -> `OCREngine` -> `VisionClient` -> live TCP loopback `HTTPServer` -> atomic disk export via `save_artifacts()`. Achieved 100% statement coverage on `core/engine.py` alongside `engine.close()` lifecycle coverage.
- **DOCX CommonMark/GFM AST Fidelity Coverage (`tests/test_docx_export.py`)**: Added targeted unit tests covering GFM table cell horizontal alignment (`WD_ALIGN_PARAGRAPH.LEFT/CENTER/RIGHT`), rich inline cell styling (bold, italic, strikethrough, code run), paragraph softbreak vs hardbreak separation, empty and 0-column table handling, unrecognized AST node fallback, and mixed-status multi-page break boundary fidelity.
- **Gitignore Coverage Pattern Tightening (`.gitignore`)**: Tightened coverage exclusion pattern to `.coverage` and `.coverage.*`, ensuring `.coveragerc` is preserved and tracked.

---

### Retry Handling & Golden Response Fixtures (September 20, 2026)
*Focus: Test suite cleanup, dead code removal, live GLM-OCR response fixture capture, and mock schema alignment. (Internal/test infrastructure; no user-facing behavior change).*
- **Cleaned Up Retry Loop (`core/client.py`)**: Removed unreachable fallback code and unused variables after the retry loop, and added an assertion for unexpected loop exits.
- **Live GLM-OCR Response Fixtures (`tests/fixtures/`)**: Spun up local managed `llama-server` (CUDA b10930) with `GLM-OCR-Q8_0.gguf` and `mmproj`; captured empirical wire responses (`real_glm_ocr_response.json` and HTTP 400 error `real_glm_ocr_error_response.json`) to serve as golden references for test mocks.
- **GUI Mock Schema Alignment (`tests/test_gui.py`)**: Corrected mock `VisionClient.complete()` return value from an invalid `{"choices": []}` array to a valid single-choice response schema matching real wire output.

---

### v1.1.0 — Microsoft Word (.docx) Export & GFM Table Prompt Hardening (September 17, 2026)
*Focus: Native Word document generation from OCR CommonMark/GFM AST, tabular formatting fidelity, write-path sanitization widening, and frozen bundle distribution. (Additive; no breaking changes).*
- **Native DOCX Export Engine (`core/docx_export.py`)**: Implemented pure-Python CommonMark and GFM AST converter (`python-docx` + `markdown-it-py`) translating OCR Markdown into clean Word documents with styled headings, inline formatting (bold, italic, inline code), blockquotes, lists, verbatim code blocks, and full table support (including header repeat across pages `w:tblHeader` and row split prevention `w:cantSplit`). Multi-page OCR documents insert page breaks strictly between pages.
- **GFM Table Prompt Instruction (`core/models.py`)**: Updated default text transcription prompt preset (`PROMPT_PRESETS["text"]`) to explicitly instruct GLM-OCR to format tabular, grid, or checklist content (including checkbox columns) using GFM pipe tables (`| ... |`), directly feeding table AST nodes to the DOCX converter.
- **Write-Path Exception Sanitization Widening (`core/formatter.py`)**: Unified exception handling across all three export formats (`markdown`, `json`, `docx`) with `_reconstruct_sanitized_exception()`, ensuring filesystem path redaction on disk write errors preserves `errno` without causing `TypeError`.
- **CLI & GUI Integration**: Added `-f docx` to `cli/main.py` supporting stdout piping (with TTY safety check) and directory exports. Added 2-option export selector (Markdown & JSON vs Word Document) in GUI Studio (`gui/app.py`) with per-document fault isolation during batch export.
- **Portable Distribution & Verification Tooling**: Bundled `docx` and `markdown_it` templates in PyInstaller spec (`build_portable.spec`), added template existence checks to `scripts/build_portable.py`, and implemented permanent empirical test suite `scripts/verify_frozen_docx.py` confirming 100% source vs frozen output parity.

---

### Security Hardening Pass (Loopback Host Binding, Proxy Defense, JSON Path & Error Sanitization)
*Focus: Defense-in-depth isolation, loopback binding enforcement, proxy interception prevention, and path sanitization in JSON exports.*
- **Explicit Loopback Host Binding**: Added explicit `"--host", "127.0.0.1"` to `llama-server` subprocess launch in `core/server_manager.py`, eliminating reliance on upstream binary default host behavior.
- **Proxy Interception Defense**: Set `trust_env = False` on `requests.Session` instances in `core/client.py` and `core/server_manager.py`, guaranteeing OS-level proxy environment variables (`HTTP_PROXY`/`HTTPS_PROXY`) cannot intercept local loopback inference traffic.
- **JSON Export Path & Error Sanitization**: Added `sanitize_export_error()` to `core/formatter.py` to redact absolute local filesystem paths embedded within error messages (`data["error"]` and `page["error"]`) when `sanitize_path=True`. Ensured single-file CLI JSON output routes through `format_output()`.

---

### CLI Diagnostic Health-Check (`--doctor`)
*Focus: Operational self-diagnostics, hardware capability reporting, runtime validation, and end-to-end vision probing.*
- **Standalone Diagnostic Flag**: Added `--doctor` flag to `AksaraSight-CLI` (`AksaraSight-CLI.exe` / `python -m cli.main`).
- **Health Checks**: Evaluates configuration sanity, hardware/GPU detection (`detect_hardware()`), runtime installation status (managed build vs custom binary), server reachability (`probe_server_health()`), and end-to-end multimodal inference (`OCREngine.verify_backend()` with 1x1 test image probe).
- **Executable Rebrand**: Renamed CLI target to `AksaraSight-CLI.exe` in `build_portable.spec` and `scripts/build_portable.py` for branding consistency.

---

### Serving Configuration & Multimodal Self-Test Hardening
*Focus: Verified serving arguments, 1x1 multimodal probe, session caching, and local-GGUF mmproj safeguard.*
- **Multimodal Startup Probe**: Added `VisionClient.verify_multimodal_support()` using a 1x1 test PNG to detect text-only servers (e.g. missing `mmproj`) before document processing.
- **Session Caching & Lifecycle Invalidation**: Cached probe result in `OCREngine._multimodal_verified`; wired invalidation to `ServerManager.start()`/`stop()`, external server adoption, settings changes, and server status transitions.
- **Local GGUF mmproj Safeguard**: Added auto-detection for adjacent `*mmproj*.gguf` files in `core/server_manager.py` with an explicit warning if missing.
- **CLI & GUI Wiring**: Wired `verify_backend()` to run once prior to batch processing in CLI and before first job in GUI session.
- **Documentation Refinements**: Softened absolute claims in `README.md`, clarified SHA-256 digest scope for Managed Runtime binaries vs model weights, and documented explicit manual server commands.

---

### Accessibility & UI Improvements
*Focus: First-run clarity, keyboard accessibility, preview accuracy, and visual polish.*
- **Friendly Error Messages**: Added `_friendly_err()` in the GUI to translate raw OS exceptions (`WinError 2`, `ConnectionError`) into human-readable footer notices while preserving full stack traces in diagnostic logs.
- **Keyboard Navigation**: Bound `<Escape>` to cleanly dismiss `SettingsWindow` and `SecurityConfirmationDialog`.
- **Processed DPI Tracking**: Added `QueueItem.processed_dpi` to record exact render resolution; displays a dynamic staleness warning (`⚠ processed @... DPI`) if global settings are changed after processing.
- **Indeterminate Progress Lifecycle**: Animated progress bar pulses in indeterminate mode during initial page rasterization before switching smoothly to determinate per-page fractions.
- **Preview Disclaimer**: Added explanatory note clarifying the difference between styled Text Preview and exact Raw Markdown.
- **A11y Verification**: Re-verified WCAG 2.1 AA contrast compliance across UI theme color pairs.

---

### Test Coverage & Error Handling Improvements
*Focus: Unmocked subprocess execution, end-to-end integration, and boundary testing.*
- **PDF Downscaling Guard**: Enforced `max_image_dimension` downscaling on rendered PDF rasters in `_process_pdf()`, ensuring multi-megapixel blueprint PDFs cannot bypass memory limits.
- **Subprocess Smoke Tests**: Added automated tests verifying isolated package launches: `python -m gui -h`, `python -m cli.main --help`, and `scripts/smoke_test_gui.py`.
- **Real Loopback Integration**: Added live TCP socket integration test verifying `ServerManager` health probing against an active server.
- **Atomic Persistence Edge Cases**: Added fault-injection tests validating `.tmp` file cleanup on disk write failures.

---

### Data Integrity & Edge Case Fixes
*Focus: Elimination of silent failures, boundary state preservation, and disk atomicity.*
- **Null-Content Handling**: Refactored `_parse_response()` in `core/client.py` so null model messages raise `ResponseParsingError` rather than silently emitting blank successful pages.
- **Boundary-Staged Settings**: Settings changed mid-document in Preferences are safely queued and only applied at clean document boundaries; unified CLI/GUI `JobConfig` parity.
- **Atomic File Exports**: Artifact exports write to `.md.tmp` and `.json.tmp` before performing atomic `Path.replace()`, preventing corrupt or partial files on interrupted writes.
- **Zero-Page Guard**: Empty document results explicitly resolve to `JobStatus.FAILED`.

---

### GUI Design Refinement & Theme Architecture
*Focus: Elimination of rendering artifacts and clean module DAG.*
- **Theme Decoupling**: Moved UI color tokens into independent `gui/theme.py` to prevent a circular import when invoking `python -m gui.app`.
- **Segmented Control Polish**: Removed default Tkinter grey borders (`border_width=0`) and aligned canvas background colors (`align_segmented_button_corners()`), eliminating 1px outer corner clipping on high-DPI Windows displays.

---

### Managed Runtime Support
*Focus: Zero-setup local inference without requiring manual llama.cpp installation.*
- **Hardware Detection**: Implemented `core/hardware.py` with zero-dependency NVIDIA GPU detection (`nvidia-smi` + `nvcuda.dll` ctypes probe with strict CUDA 12.4+ driver checks) and Vulkan discrete GPU detection (`vulkan-1.dll`). Added `--detect-hardware` CLI flag.
- **Verified Downloader**: Implemented `core/runtime_manager.py` downloading pinned release build `b10930`. Added streaming download to `.part` files, strict SHA-256 digest validation against pinned known hashes, Zip-Slip path traversal protection, staging directories, and atomic installation to `%LOCALAPPDATA%\AksaraSight\runtimes\`.
- **GUI Supervision Integration**: Added *Runtime Source* segmented control (`Managed (Auto)` vs `Custom Path`), live status badges, download progress bar, force-reinstall capability, and interactive hardware refresh.
- **Subprocess Security Hardening**: Enforced explicit subprocess CWD isolation to prevent DLL search hijacking on Windows, prioritized `System32` for `nvidia-smi`, enforced fail-closed pinned hash verification, and added post-install `.zip` cleanup.

---

### Code Simplification & Cleanup
*Focus: Elimination of speculative abstractions, dead code, and over-engineering.*
- **Refactoring & Deduplication**: Deduplicated single- vs multi-frame image loading, consolidated theme palettes, standardized on JPEG base64 encoding, removed pass-through wrapper methods and obsolete method aliases, inlined unique stem resolution, and pruned unused imports.
- **Ingestion & Environment Cleanup**: Removed unused in-memory bytes/buffer ingestion paths across pipeline and engine (enforcing clean filesystem paths), pruned base64 image retention plumbing from memory in favor of on-demand rasterization, and established canonical `OCR_*` environment variable precedence with deprecation logging for legacy names.

---

### Performance Improvements
*Focus: Memory bounding, responsive GUI threading, and lazy rendering.*
- **Pipeline & Ingestion**: Wired runtime DPI end-to-end, introduced configurable `max_image_dimension: int = 2048` cap with Lanczos downscaling (reducing VRAM by 60% with 100% text match), replaced unbounded CLI batch memory accumulation with streaming booleans, and deduplicated Markdown serialization.
- **GUI Memory & Rendering**: Refactored preview pane to lazily render only the active tab on-demand, implemented on-demand disk rasterization for image previews (`retain_images=False`), and cached formatted file sizes.
- **Responsiveness & Polling**: Implemented adaptive polling backoff (50ms → 250ms for worker queue; 2s → 10s for server health), background daemon thread discovery for dropped folders, 25-item chunked UI insertion, background export thread with concurrency locking, and cross-thread Tkinter condition-lock routing via `_ui_callback_queue`.

---

### Security Hardening & Process Isolation
*Focus: OS process isolation, race conditions, and configuration persistence.*
- **Win32 Job Object**: Bound managed `llama-server.exe` subprocesses to a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`, guaranteeing immediate process termination even upon hard application crashes.
- **Settings Propagation**: Fixed client endpoint synchronization and implemented safe inter-document boundary settings staging.
- **Safe .env Round-Tripping**: Single-quoted string serialization in `Settings.save_to_env()` ensuring paths with spaces, `#`, or apostrophes round-trip cleanly without backslash corruption on Windows.
- **Process Cleanup**: Added `atexit` hooks and active launch cancellation during server startup.

---

### GUI Redesign & Server Supervision
*Focus: Professional desktop studio experience and server lifecycle management.*
- **Dark Theme**: Replaced high-contrast theme with dark palette (`#121417`, `#1a1d21`, `#2e6e91`), colored-dot status badges (`●`), and on-device privacy guarantee.
- **4-Tab Preview Pane**: Restructured previews into Raw Markdown, rich Text Preview, paginated Image Preview, and structured JSON Tree.
- **Real Per-Page Progress**: Wired engine progress callbacks thread-safely to a responsive progress bar.
- **Server Manager**: Implemented headless `ServerManager` with non-blocking health probing and dynamic status controls (`● READY`, `● STARTING`, `● OFFLINE`, `● ERROR`).
- **Preferences Modal**: Created `SettingsWindow` and custom dark-themed `SecurityConfirmationDialog`.

---

### Initial Security Hardening
*Focus: Attack surface reduction, loopback boundaries, and path privacy.*
- **Enforced Loopback**: Default endpoint allowlist restricted strictly to `localhost`, `127.0.0.1`, and `::1`; non-loopback addresses require explicit `--allow-remote` opt-in.
- **Sanitized Filenames**: Stripped illegal characters and sanitized legacy Windows reserved device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`).
- **Decompression-Bomb Defense**: Implemented `MAX_RASTER_PIXELS` (89,478,485 px) dimension preflight in PDF rasterization.
- **Cooperative Cancellation**: Added inter-page cancellation (`threading.Event`) and `--max-pages` cap.
- **Privacy Sanitization**: Automatically relativized file paths in exported `.json` artifacts against working/home directories.

---

### Local Backend Integration
*Focus: Empirical hardware validation and baseline establishment.*
- Verified live inference against local `llama-server` (build 10930) and `ggml-org/GLM-OCR-GGUF` on NVIDIA RTX 3050 Laptop GPU (6GB VRAM).
- Established default `-c 8192 --parallel 1` configuration, capping active VRAM to 2.18 GB (well below the 3.5 GB target).
- Standardized default rasterization at 100 DPI (~2.7s/page) to balance latency and character fidelity.
- Documented GLM-OCR model limitation with unclosed inline LaTeX math delimiters on `$DIGIT` currency amounts.

---

### Desktop GUI Studio
*Focus: Desktop interface implementation.*
- Implemented CustomTkinter desktop interface (`gui/app.py`) with native drag-and-drop (`tkinterdnd2`), Tcl 9 Windows path escape normalization, thread-safe background queue worker, scrollable queue manager, and artifact export actions.

---

### Command-Line Interface (CLI)
*Focus: Headless automation and pipeline integration.*
- Implemented scriptable CLI (`cli/main.py`) powered by `argparse`, supporting stdout streaming (`-q`), recursive batch processing (`-o`), format selection (`-f markdown|json|both`), and structured exit codes (`0`, `1`, `2`).

---

### Core Engine & Pipeline Foundation
*Focus: Local inference foundation.*
- Implemented `config/settings.py` (dataclass with `.env` loading and validation) and `core/models.py` (`JobStatus`, `OutputFormat`, `JobConfig`, `PageResult`, `OCRResult`).
- Implemented `core/pipeline.py` (two-stage image validation, `pypdfium2` PDF rasterization with thread locks, RGB base64 conversion).
- Implemented `core/client.py` (universal OpenAI-compatible Vision API client with persistent connection pooling and exponential jitter backoff).
- Implemented `core/engine.py` (`OCREngine` orchestrator with per-page fault isolation) and `core/formatter.py` (Markdown/JSON artifact disk exporters).
