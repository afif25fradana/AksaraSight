# AksaraSight: Technical Documentation & Architecture

This document provides in-depth technical specifications, architecture notes, configuration details, and developer workflows for engineers, system administrators, and contributors.

---

## Table of Contents

1. [Architecture & Codebase Layout](#architecture--codebase-layout)
2. [CLI Reference & Automation](#cli-reference--automation)
3. [Configuration & Environment Variables](#configuration--environment-variables)
4. [Custom Runtime & Manual Server Setup](#custom-runtime--manual-server-setup)
5. [Security, Network Policy & Process Lifecycles](#security-network-policy--process-lifecycles)
6. [Output Formats & Data Payloads](#output-formats--data-payloads)
7. [Performance, Latency & Known Model Quirks](#performance-latency--known-model-quirks)
8. [Logging Architecture & Runtime Diagnostics](#logging-architecture--runtime-diagnostics)
9. [Testing, Build Verification & Portable Packaging](#testing-build-verification--portable-packaging)

---

## Architecture & Codebase Layout

AksaraSight strictly isolates presentation layers from domain logic. The CLI and Desktop GUI are thin consumers; all OCR execution, base64 payload encoding, image downscaling, and HTTP client interactions are centralized in `core/`.

```
AksaraSight/
├── core/                  # Shared engine core
│   ├── engine.py          # OCREngine orchestrating the ingestion-to-artifact pipeline
│   ├── client.py          # VisionClient communicating with OpenAI-compatible backends
│   ├── pipeline.py        # PDF/image rasterization, Lanczos downscaling, and pixel guards
│   ├── formatter.py       # Artifact generation (Markdown, JSON, DOCX) & atomic writes
│   ├── docx_export.py     # Markdown-to-DOCX conversion with OOXML table fidelity
│   ├── hardware.py        # NVIDIA CUDA, Vulkan, and CPU hardware probe
│   ├── runtime_manager.py # Managed llama-server download, SHA-256 verification, and unpack
│   ├── server_manager.py  # Local inference process lifecycle supervision and health polling
│   ├── job_object.py      # Win32 Job Object process containment (KILL_ON_JOB_CLOSE)
│   ├── models.py          # Strict dataclasses (JobConfig, PageResult, OCRResult)
│   └── constants.py       # Application constants and version single source of truth
├── cli/                   # Scriptable command-line interface
│   └── main.py            # Streaming CLI entrypoint, argument parsing, batch processor
├── gui/                   # Desktop GUI Studio (CustomTkinter)
│   ├── app.py             # Main application window and coordinator (~1,497 lines)
│   ├── queue_manager.py   # QueueManager: queue state, list selection, card widgets
│   ├── export_controller.py # ExportController: artifact exports, format resolution, export threads
│   ├── server_controller.py # ServerUIController: health polling, status pill, server actions
│   ├── worker_coordinator.py # WorkerCoordinator: background task loop and result dispatch
│   ├── image_preview.py   # ImagePreviewController: page preview rendering, zoom, pan
│   ├── preview_highlighter.py # MarkdownHighlighter: syntax highlighting and preview tabs
│   ├── security_dialog.py # SecurityConfirmationDialog: remote endpoint opt-in confirmation
│   ├── settings_window.py # SettingsWindow: runtime manager, preferences modal, backend toggle
│   └── theme.py           # Dark theme color tokens and styling helpers
├── config/                # Configuration management
│   └── settings.py        # Immutable, self-validating Settings dataclass & .env persistence
├── scripts/               # Benchmarking, smoke tests, and build verification harnesses
└── tests/                 # Automated test suite (unit, integration, and UI tests)
```

### Architectural Guarantees & Concurrency
- **Thread Safety**: `pypdfium2` PDF bindings are not thread-safe; all PDF operations are strictly serialized via `_PDFIUM_LOCK` in `core/pipeline.py`.
- **GUI Thread Isolation**: Tkinter and Tcl are single-threaded on Windows. Background worker threads never invoke UI methods directly; all cross-thread events route through `_ui_callback_queue` drained on the main loop.
- **Fail-Safe Offline Behavior**: If the local backend is unreachable or drops connection mid-document, processing stops immediately with a `ServerOfflineError` rather than routing files externally.

---

## CLI Reference & Automation

The CLI provides full scriptability, streaming stdout pipes, batch directory discovery, and diagnostic utilities.

### Invocation Syntax
```powershell
python -m cli.main [input] [options]
```

### Options & Flags

| Flag | Description | Default |
| --- | --- | --- |
| `input` | Path to file or directory to process. | *Required* |
| `-o, --output` | Output directory. Required when `input` is a directory; omit for stdout. | `None` |
| `-f, --format` | Export format: `markdown`, `json`, `both`, or `docx`. | `markdown` |
| `-p, --prompt-mode` | Preset prompt: `text`, `table`, or `formula`. | `text` |
| `--prompt` | Custom model instruction prompt (overrides preset). | `None` |
| `-r, --recursive` | Recursively scan subdirectories for documents. | `False` |
| `--detect-hardware` | Probe system hardware, print recommended backend, and exit. | `False` |
| `--doctor` | Run diagnostic checklist (config, hardware, runtime, server, vision probe). | `False` |
| `--backend` | Inference backend: `llama-cpp`, `ollama`, or `vllm`. | `llama-cpp` |
| `--endpoint` | OpenAI-compatible API base URL. | `http://localhost:8080/v1` |
| `--allow-remote` | Explicitly permit non-loopback endpoints (see Security). | `False` |
| `--max-pages` | Maximum pages to process per document. | `None` (unlimited) |
| `--dpi` | PDF rasterization DPI (higher = clearer text, higher latency). | `100` |
| `-q, --quiet` | Suppress log messages; emit strictly transcription output. | `False` |

**Supported Input Formats:** `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.webp`, `.pdf`.

**Exit Codes:**
- `0`: Success (all documents processed).
- `1`: Fatal error, network disconnect, or offline abort.
- `2`: Partial failure (some documents failed in a batch run).

### Automation Examples

```powershell
# Diagnostic health check
python -m cli.main --doctor

# Clean piping to file or downstream script (suppressing info logs)
python -m cli.main document.pdf --quiet > output.md

# Batch convert an entire folder recursively to Word documents
python -m cli.main .\scans\ -o .\docx_output\ -f docx --recursive

# High-resolution conversion with a 5-page ceiling
python -m cli.main invoice.pdf -o .\output\ --dpi 150 --max-pages 5
```

---

## Configuration & Environment Variables

Settings are loaded from environment variables or a `.env` file via `config/settings.py`. All canonical variables use the `OCR_` prefix (legacy unprefixed variables work with a deprecation warning).

| Variable | Default | Description |
| --- | --- | --- |
| `OCR_RUNTIME_MODE` | `managed` | `managed` (auto-detect and supervise) or `custom` (manual external server). |
| `OCR_MANAGED_BACKEND_OVERRIDE` | `auto` | Force managed backend: `auto`, `cuda`, `vulkan`, or `cpu`. |
| `OCR_LLAMA_SERVER_PATH` | None | Absolute path to `llama-server.exe` when in `custom` mode. |
| `OCR_MODEL_REPO` | `ggml-org/GLM-OCR-GGUF` | Hugging Face repository for GGUF model weights. |
| `OCR_AUTO_START_SERVER` | `false` | Automatically start the managed server when the GUI launches. |
| `OCR_BACKEND` | `llama-cpp` | Inference engine type: `llama-cpp`, `ollama`, or `vllm`. |
| `OCR_ENDPOINT` | `http://localhost:8080/v1` | Local OpenAI-compatible API endpoint URL. |
| `OCR_TIMEOUT` | `60.0` | Network request timeout in seconds. |
| `OCR_MAX_RETRIES` | `2` | Retry attempts on transient network or 5xx/429 errors. |
| `OCR_ALLOW_REMOTE` | `false` | Opt-in to permit non-loopback endpoints. |
| `OCR_DPI` | `100` | Rasterization DPI for PDF pages. |
| `OCR_MAX_PAGES` | None | Global page cap per document (`None` = all pages). |
| `OCR_MAX_IMAGE_DIMENSION` | `2048` | Longest-edge dimension cap (512–8192 px) to protect VRAM. |

A documented template is provided in [`.env.example`](.env.example).

---

## Custom Runtime & Manual Server Setup

If you maintain an independent `llama.cpp`, Ollama, or vLLM deployment, you can configure AksaraSight to connect to your existing instance.

### Running standalone `llama-server`

GLM-OCR is a vision-language model requiring both text weights and multimodal projector weights (`mmproj`):

```powershell
# Option A: Automatic Hugging Face resolution (llama.cpp b11361+ auto-downloads matching mmproj)
llama-server -hf ggml-org/GLM-OCR-GGUF --host 127.0.0.1 --port 8080 -ngl 99 -c 8192 --parallel 1

# Option B: Local GGUF files (explicit --mmproj is REQUIRED)
llama-server -m path/to/GLM-OCR-Q8_0.gguf --mmproj path/to/mmproj-GLM-OCR-Q8_0.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 8192 --parallel 1
```

> **VRAM Configuration Tip**: While raw GGUF weights are ~1.36 GB (~1.8 GB VRAM), `llama-server` defaults to `n_slots=4` and `n_ctx_slot=40192`, which pre-allocates an extra ~2.0 GB of unified KV cache and balloons VRAM to >4.2 GB. Launching with `-c 8192 --parallel 1` caps context to 8k tokens and single-slot concurrency, holding VRAM to ~2.18 GB.

---

## Security, Network Policy & Process Lifecycles

- **Loopback Restriction by Default**: AksaraSight restricts network requests to loopback interfaces (`127.0.0.1`, `localhost`, `::1`). External endpoints require explicit `--allow-remote` or `OCR_ALLOW_REMOTE=true`.
- **Explicit IPv4 Loopback Binding (`--host 127.0.0.1`)**: When spawning managed `llama-server` instances, `ServerManager` explicitly passes `--host 127.0.0.1` (`core/server_manager.py`), ensuring the inference server binds strictly to the local host interface rather than wildcard `0.0.0.0`.
- **Proxy Bypass Prevention (`trust_env = False`)**: HTTP client sessions in `VisionClient` (`core/client.py`) and `ServerManager` (`core/server_manager.py`) explicitly set `trust_env = False` to prevent ambient system proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`) from intercepting or redirecting loopback traffic.
- **Win32 Job Object Supervision**: On Windows, the managed `llama-server` process runs inside a Win32 Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`. If the GUI or CLI is terminated, the OS kernel terminates child server processes automatically.
- **Cryptographic Verification**: Managed runtime binaries and CUDA support DLLs downloaded from GitHub release assets are verified against pinned SHA-256 digests prior to archive extraction.
- **Zip-Slip Protection**: Directory extraction asserts canonical path boundaries, rejecting archives containing directory traversal attacks (`../`).
- **Pixel-Bomb Defense**: Images and PDF pages exceeding 89,478,485 pixels (`MAX_RASTER_PIXELS`) are rejected prior to rasterization to eliminate decompression memory bombs.
- **Atomic File Writes**: Exports write to `.tmp` files first, renaming them into place atomically to prevent partial writes. The exporter relativizes paths in JSON output to prevent leaking username paths.

---

## Output Formats & Data Payloads

- **Markdown (`.md`)**: Raw transcription retaining headings, Markdown pipe tables, list hierarchies, and LaTeX inline equations.
- **Word Document (`.docx`)**: Generated via `core/docx_export.py` using OOXML styling. Tables include repeating header rows (`w:tblHeader`) and row-split prevention (`w:cantSplit`). Document styles map headings to native Word levels (`Heading 1–3`), and page breaks are inserted strictly between non-empty scanned pages.
- **Structured JSON (`.json`)**: Contains complete processing metadata:
  ```json
  {
    "document": "sample.pdf",
    "total_pages": 2,
    "processed_dpi": 100,
    "elapsed_seconds": 5.4,
    "pages": [
      {
        "page_number": 1,
        "status": "success",
        "duration_seconds": 2.7,
        "text": "# Transcribed Heading\n\nContent..."
      }
    ]
  }
  ```

---

## Performance, Latency & Known Model Quirks

- **DPI vs. Latency Trade-Off**:
  - `100 DPI` (Default, ~1.7 MP): ~2.7s per page on an NVIDIA RTX 3050 Laptop GPU (60W). Provides reliable recognition on clear, standard printed text.
  - `150 DPI` (~3.8 MP): ~5.6s per page. Recommended for dense small-print receipts or low-resolution scans.
  - `72 DPI`: ~1.5s per page. Faster throughput, but may introduce OCR distortion on fine print.
- **Currency Symbol Delimiter Anomaly (`$DIGIT`)**:
  When currency figures lack whitespace (e.g., `$100.00` or `$1,250.00`), GLM-OCR's tokenizer misinterprets `$` before digits as an unclosed inline LaTeX math delimiter, and post-processing filters strip the symbol (yielding `.00` or `,250.00`). Figures formatted with whitespace (`$ 100.00`) or standard ISO currency codes (`USD 100.00`) transcribe accurately. Financial workflows should verify unspaced dollar amounts.
- **Page-Boundary Cancellation**: Active HTTP vision requests cannot be safely terminated mid-transfer without destroying the underlying HTTP connection pool. Cancelling multi-page jobs completes the current in-flight page before gracefully halting.

---

## Logging Architecture & Runtime Diagnostics

### Application File Logging
When running as a packaged desktop application, runtime logs are written directly to disk:
- **Destination**: `%LOCALAPPDATA%\AksaraSight\logs\app.log`
- **Log Level Routing**: The root logger is initialized at `INFO` to record operational lifecycle events. To capture diagnostic troubleshooting details without polluting logs with high-volume third-party library noise (such as `urllib3`, `PIL`, or `customtkinter`), `DEBUG` logging is specifically enabled for internal application namespaces (`gui` and `core`). Unhandled crashes are intercepted via `sys.excepthook` and recorded with full tracebacks.
- **Log Rotation Policy**: Log file growth is bounded using a `RotatingFileHandler` configured with a 5 MB maximum file size (`maxBytes=5242880`) and up to 3 backup archives (`backupCount=3`, preserving `app.log.1`, `app.log.2`, and `app.log.3`).
- **Multi-Instance Concurrency on Windows**: Windows enforces mandatory file locks on open file handles. When two application instances run concurrently and share the same log file, log rotation cannot rename active log files (`PermissionError`). Python's logging handler catches this condition internally, deferring rotation until the secondary process releases its handle. Standard single-instance execution rotates logs cleanly without interruption.

### Hardware Pre-Flight & Cold-Start Diagnostics
GLM-OCR inference under the default 8,192 token context window (`-c 8192 --parallel 1`) requires approximately 2.2 GB of GPU VRAM. AksaraSight implements early hardware pre-flight checks to alert users before inference begins:
- **Asynchronous Hardware Pre-Warming**: Both the CLI (`cli/main.py`) and Desktop GUI (`gui/app.py`) invoke `start_hardware_prewarm()` on cold start. This initializes hardware detection (querying `nvidia-smi` and Vulkan physical devices) on a background daemon thread, populating an in-memory cache without delaying application startup or blocking UI rendering.
- **Low-VRAM Pre-Flight Warning**: When an NVIDIA GPU is detected with less than 2,200 MB of dedicated VRAM, an advisory warning is logged alerting the user that the server may experience CUDA out-of-memory errors or require partial CPU offloading. By checking cached profiles during server startup without acquiring blocking locks, the warning evaluates immediately without freezing process supervision.

---

## Testing, Build Verification & Portable Packaging

### Running the Test Suite
The test suite is configured via `pytest.ini`:
1. **Core & CLI Suite**: Headless unit, functional, and integration tests covering document ingestion, formatting, hardware detection, model client, controllers, and runtime supervision. Runs on both Linux and Windows.
2. **Desktop GUI Suite**: Tkinter and CustomTkinter desktop interface tests, run on Windows.

Run tests from the repository root:

```powershell
# Core & CLI test suite (headless, verified green on Linux CI)
python -m pytest --ignore=tests/test_gui.py

# Complete test suite (verified green on Windows CI)
python -m pytest
```

### Code Style & Linting
CI lints the codebase with Ruff (`ruff check .`). No static type checker is configured or run.

### Build Verification Scripts
For standalone binary distributions created with `scripts/build_portable.py`:
- `python scripts/verify_frozen_build.py`: Validates CLI version output, offline hardware detection, input error handling, Win32 window table rendering/visibility, and file logging in `%LOCALAPPDATA%\AksaraSight\logs\app.log`.
- `python scripts/verify_frozen_docx.py`: Asserts OOXML table structure, `_internal` asset bundling, and performs a 100% AST parity diff between source and frozen DOCX exports.

### Compiling Standalone Portable Distribution
To bundle the application into a standalone Windows x64 distribution:
```powershell
pip install -r requirements-build.txt
python scripts/build_portable.py
```
This produces `dist/AksaraSight-v<version>-windows-x64.zip` containing `AksaraSight.exe`.
