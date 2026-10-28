# AksaraSight: Technical Documentation & Architecture

This document provides in-depth technical specifications, architecture notes, configuration details, and developer workflows for engineers, system administrators, and contributors.

---

## Table of Contents

1. [Architecture & Codebase Layout](#architecture--codebase-layout)
2. [CLI Reference & Automation](#cli-reference--automation)
3. [Web API Reference & SSE Contract](#web-api-reference--sse-contract)
4. [Configuration & Environment Variables](#configuration--environment-variables)
5. [Custom Runtime & Manual Server Setup](#custom-runtime--manual-server-setup)
6. [Security, Network Policy & Process Lifecycles](#security-network-policy--process-lifecycles)
7. [Output Formats & Data Payloads](#output-formats--data-payloads)
8. [Performance, Latency & Known Model Quirks](#performance-latency--known-model-quirks)
9. [Logging Architecture & Runtime Diagnostics](#logging-architecture--runtime-diagnostics)
10. [Testing, Build Verification & Portable Packaging](#testing-build-verification--portable-packaging)

---

## Architecture & Codebase Layout

AksaraSight strictly isolates presentation layers from domain logic. The CLI and Web UI are thin consumers; all OCR execution, base64 payload encoding, image downscaling, and HTTP client interactions are centralized in `core/`.

```
AksaraSight/
├── core/                  # Shared engine core
│   ├── engine.py          # OCREngine orchestrating the ingestion-to-artifact pipeline
│   ├── client.py          # VisionClient communicating with OpenAI-compatible backends
│   ├── pipeline.py        # PDF/image rasterization, Lanczos downscaling, and pixel guards
│   ├── formatter.py       # Artifact generation (Markdown, JSON, DOCX) & atomic writes
│   ├── docx_export.py     # Markdown-to-DOCX conversion with OOXML table fidelity
│   ├── hardware.py        # NVIDIA CUDA, Vulkan, and CPU hardware probe
│   ├── diagnostics.py     # 5-stage system diagnostics & hardware health probe (--doctor)
│   ├── runtime_manager.py # Managed llama-server download, SHA-256 verification, and unpack
│   ├── model_manager.py   # Pinned GGUF model weight downloader and SHA-256 verifier
│   ├── server_manager.py  # Local inference process lifecycle supervision and health polling
│   ├── job_object.py      # Win32 Job Object process containment (KILL_ON_JOB_CLOSE)
│   ├── models.py          # Strict dataclasses (JobConfig, PageResult, OCRResult)
│   └── constants.py       # Application constants and version single source of truth
├── cli/                   # Scriptable command-line interface
│   └── main.py            # Streaming CLI entrypoint, argument parsing, batch processor
├── web/                   # Browser-based local workspace (FastAPI & React)
│   ├── app.py             # FastAPI application factory, API routes, and SSE streaming
│   ├── orchestrator.py    # Batch queue orchestration, SSE progress dispatch, and worker threads
│   ├── security.py        # Loopback-only Host header, port pinning, and origin security middleware
│   ├── __main__.py        # Module entrypoint (`python -m web`)
│   └── static/            # Pre-built React production frontend SPA assets
├── frontend/              # Local Web UI Single Page Application source (React 19, TS, Vite)
├── config/                # Configuration management
│   └── settings.py        # Immutable, self-validating Settings dataclass & .env persistence
├── docs/                  # Project documentation and architectural records
│   ├── adr/               # Architecture Decision Records (ADR-0001 through ADR-0010)
│   └── images/            # Documentation screenshots and UI assets
├── scripts/               # Benchmarking, smoke tests, and build verification harnesses
└── tests/                 # Automated test suite (unit, functional, and integration tests)
```

### Architectural Decision Records (ADRs)
Formal engineering decisions, context, trade-offs, and rejected alternatives are maintained as modular Michael Nygard ADRs under [`docs/adr/`](docs/adr/):
- **[ADR-0001](docs/adr/0001-decoupled-local-inference-via-openai-compatible-http-backend.md)**: Decoupled local inference via OpenAI-compatible HTTP backend.
- **[ADR-0002](docs/adr/0002-migration-from-native-desktop-gui-to-local-web-ui-workspace.md)**: Migration from native desktop GUI to local Web UI workspace.
- **[ADR-0003](docs/adr/0003-zero-dependency-hardware-probe-and-managed-runtime-pinning.md)**: Zero-dependency hardware probe and managed runtime pinning.
- **[ADR-0004](docs/adr/0004-thread-safe-pdfium-rasterization-and-pipeline-guards.md)**: Thread-safe PDFium rasterization and pipeline guards.
- **[ADR-0005](docs/adr/0005-strict-loopback-security-port-pinning-and-anti-exfiltration.md)**: Strict loopback security, port pinning, and anti-exfiltration.
- **[ADR-0006](docs/adr/0006-asynchronous-event-loop-offloading-and-memory-governance.md)**: Asynchronous event loop offloading and memory governance.
- **[ADR-0007](docs/adr/0007-per-job-dynamic-configuration-and-unified-extraction-pipeline.md)**: Per-job dynamic configuration and unified extraction pipeline.
- **[ADR-0008](docs/adr/0008-real-time-model-lifecycle-streaming-and-view-transition-isolation.md)**: Real-time model lifecycle streaming and CSS view transition isolation.
- **[ADR-0009](docs/adr/0009-subprocess-proxy-isolation-event-loop-offloading-and-focus-trapping.md)**: Subprocess proxy isolation, event loop offloading, and focus trapping.
- **[ADR-0010](docs/adr/0010-core-engine-encapsulation-runtime-path-decoupling-and-concurrency-hardening.md)**: Core engine encapsulation, runtime path decoupling, and concurrency hardening.

### Architectural Guarantees & Concurrency
- **Thread Safety**: `pypdfium2` PDF bindings are not thread-safe; all PDF operations are strictly serialized via `_PDFIUM_LOCK` in `core/pipeline.py`.
- **Worker Isolation**: Document OCR jobs run on background threads managed by `web/orchestrator.py`, streaming real-time progress over SSE without blocking FastAPI request handling.
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
| `-v, --version` | Show program's version number and exit. | `N/A` |

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

### Web UI Server Options (`python -m web`)

The Web UI workspace entrypoint accepts the following flags:

| Flag | Description | Default |
| --- | --- | --- |
| `--host` | Bind interface (strictly enforced loopback). | `127.0.0.1` |
| `--port` | Port number for the Web UI server. | `8000` |
| `--dev` | Allow Vite frontend dev server origins (port 5173). | `False` |
| `--reload` | Auto-reload Uvicorn server on code changes. | `False` |
| `--no-browser` | Prevent auto-launching default browser on application start. | `False` |

---

## Web API Reference & SSE Contract

AksaraSight provides a lightweight local REST API and Server-Sent Events (SSE) stream powered by FastAPI (`web/app.py` and `web/orchestrator.py`). All endpoints strictly enforce loopback origin headers.

### Diagnostics & Server Supervision
- `GET /health`: Health check returning server status, backend mode, and endpoint diagnostics.
- `GET /api/doctor`: Returns 5-stage system diagnostics (configuration, hardware, runtime, server reachability, multimodal probe).
- `POST /api/doctor`: Triggers a fresh live system diagnostic re-probe.
- `GET /api/server/status`: Current managed server lifecycle state (`offline`, `starting`, `ready`, `error`).
- `POST /api/server/start`: Launches the managed local `llama-server` process with hardware-optimized arguments.
- `POST /api/server/stop`: Stops the local `llama-server` process gracefully.
- `GET /api/server/logs/stream`: SSE stream broadcasting live `llama-server` process stdout/stderr logs.

### Settings & Configuration
- `GET /api/settings`: Returns the active configuration dictionary (with sensitive paths sanitized).
- `PATCH /api/settings`: Updates mutable runtime parameters (`backend`, `local_endpoint`, `allow_remote`, `runtime_mode`, `managed_backend_override`, `llama_server_path`, `dpi`, `max_image_dimension`, `max_tokens`, `timeout`, `max_retries`, `auto_start_server`, `model_repo`).
- `POST /api/dialog/file`: Triggers a native Windows file or folder browse dialog to select binaries or directories.

### Document Pipeline & Extraction
- `GET /api/documents`: Lists all uploaded documents in the session queue.
- `POST /api/documents`: Multipart upload for documents (`.pdf`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.webp`).
- `GET /api/documents/{job_id}/pages/{page}/preview`: Renders and returns a PNG page image preview.
- `POST /api/documents/{job_id}/extract`: Enqueues document extraction with request payload `{"prompt_mode": "text"|"table"|"formula", "dpi": 100|150}`.
- `POST /api/documents/{job_id}/cancel`: Requests cooperative cancellation of an active extraction job.
- `DELETE /api/documents/{job_id}`: Removes a document from the queue and cleans up cached artifacts.

### Artifact Export & Output Management
- `GET /api/documents/{job_id}/export?format=md|json|docx`: Downloads the converted document in the requested format.
- `GET /api/output`: Lists previously exported files in the designated output folder.
- `POST /api/output/open`: Opens the output folder in Windows File Explorer.
- `DELETE /api/output/{filename}`: Deletes an exported artifact from the output directory.

### Model & Runtime Management
- `GET /api/model/status`: Returns downloaded status and integrity of GLM-OCR model weights.
- `POST /api/model/download`: Initiates background download of model weights with SHA-256 verification.
- `POST /api/model/download/cancel`: Cancels an active model download and cleans partial files.
- `GET /api/runtime/status`: Returns detection and installation status of managed `llama-server` binaries.
- `POST /api/runtime/download`: Initiates background download and staging of managed llama.cpp runtime archives.
- `POST /api/runtime/download/cancel`: Cancels an active runtime download.

### Server-Sent Events (SSE) Contract (`GET /api/events`)
The frontend and external scripts subscribe to real-time events over `GET /api/events`:

| Event Name | Payload Schema | Description |
| --- | --- | --- |
| `started` | `{"job_id": str, "total_pages": int}` | Emitted when OCR begins for a document. |
| `page_progress` | `{"job_id": str, "current_page": int, "total_pages": int, "status": str}` | Emitted as each page finishes rasterization or OCR. |
| `completed` | `{"job_id": str, "elapsed_seconds": float, "pages": [...]}` | Emitted when full document finishes processing. |
| `failed` | `{"job_id": str, "error": str}` | Emitted on unrecoverable processing or server disconnection errors. |
| `cancelled` | `{"job_id": str, "pages_completed": int}` | Emitted when a job is cooperatively halted. |
| `model_download_progress` | `{"downloaded_bytes": int, "total_bytes": int, "percent": float}` | Emitted during GGUF model file retrieval. |
| `runtime_download_progress`| `{"downloaded_bytes": int, "total_bytes": int, "percent": float}` | Emitted during llama.cpp archive download/extraction. |
| `_ping` | `{"timestamp": float}` | Keep-alive heartbeat emitted every 15 seconds. |

---

## Configuration & Environment Variables

Settings are loaded from environment variables or a `.env` file via `config/settings.py`. All canonical variables use the `OCR_` prefix (legacy unprefixed variables work with a deprecation warning).

| Variable | Default | Description |
| --- | --- | --- |
| `OCR_RUNTIME_MODE` | `managed` | `managed` (auto-detect and supervise) or `custom` (manual external server). |
| `OCR_MANAGED_BACKEND_OVERRIDE` | `auto` | Force managed backend: `auto`, `cuda`, `vulkan`, or `cpu`. |
| `OCR_LLAMA_SERVER_PATH` | None | Absolute path to `llama-server.exe` when in `custom` mode. |
| `OCR_MODEL_REPO` | `ggml-org/GLM-OCR-GGUF` | Hugging Face repository for GGUF model weights. |
| `OCR_AUTO_START_SERVER` | `false` | Automatically start the managed server when the Web UI server starts. |
| `OCR_BACKEND` | `llama-cpp` | Inference engine type: `llama-cpp`, `ollama`, or `vllm`. |
| `OCR_ENDPOINT` | `http://localhost:8080/v1` | Local OpenAI-compatible API endpoint URL. |
| `OCR_TIMEOUT` | `60.0` | Network request timeout in seconds. |
| `OCR_MAX_RETRIES` | `2` | Retry attempts on transient network or 5xx/429 errors. |
| `OCR_ALLOW_REMOTE` | `false` | Opt-in to permit non-loopback endpoints. |
| `OCR_DPI` | `100` | Rasterization DPI for PDF pages. |
| `OCR_MAX_PAGES` | None | Global page cap per document (`None` = all pages). |
| `OCR_MAX_IMAGE_DIMENSION` | `2048` | Longest-edge dimension cap (512–8192 px) to protect VRAM. |
| `OCR_MAX_TOKENS` | `4096` | Maximum completion tokens allocated per OCR page (128–16384). |
| `OCR_OUTPUT_DIR` | None | Default directory for exported OCR artifacts (.md, .json, .docx). |
| `AKSARA_ENV_FILE` | None | Optional custom path to load environment variables from. |
| `HF_HOME` | None | Hugging Face cache root to discover existing local model weights. |

> **Per-Job Extraction Overrides**: While `OCR_DPI` sets the global default, individual document extraction requests (`POST /api/documents/{job_id}/extract`) accept dynamic `dpi` (100 or 150) and `prompt_mode` (`text`, `table`, or `formula`) overrides.

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

> **VRAM Configuration Tip**: While raw GGUF weights are ~1.43 GB (~1.34 GiB, ~1.8 GB VRAM), `llama-server` defaults to `n_slots=4` and `n_ctx_slot=40192`, which pre-allocates an extra ~2.0 GB of unified KV cache and balloons VRAM to >4.2 GB. Launching with `-c 8192 --parallel 1` caps context to 8k tokens and single-slot concurrency, holding VRAM to ~2.18 GB.

---

## Security, Network Policy & Process Lifecycles

- **Loopback Restriction by Default**: AksaraSight restricts network requests to loopback interfaces (`127.0.0.1`, `localhost`, `::1`). External endpoints require explicit `--allow-remote` or `OCR_ALLOW_REMOTE=true`.
- **Explicit IPv4 Loopback Binding (`--host 127.0.0.1`)**: When spawning managed `llama-server` instances, `ServerManager` explicitly passes `--host 127.0.0.1` (`core/server_manager.py`), ensuring the inference server binds strictly to the local host interface rather than wildcard `0.0.0.0`.
- **Proxy Bypass Prevention (`trust_env = False`)**: HTTP client sessions in `VisionClient` (`core/client.py`) and `ServerManager` (`core/server_manager.py`) explicitly set `trust_env = False` to prevent ambient system proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`) from intercepting or redirecting loopback traffic.
- **Win32 Job Object Supervision**: On Windows, the managed `llama-server` process runs inside a Win32 Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)`. If the Web UI or CLI process is terminated, the OS kernel terminates child server processes automatically.
- **Cryptographic Verification**: Managed runtime binaries and CUDA support DLLs downloaded from GitHub release assets are verified against pinned SHA-256 digests prior to archive extraction.
- **Zip-Slip Protection**: Directory extraction asserts canonical path boundaries, rejecting archives containing directory traversal attacks (`../`).
- **Pixel-Bomb Defense**: Images and PDF pages exceeding 89,478,485 pixels (`MAX_RASTER_PIXELS`) are rejected prior to rasterization to eliminate decompression memory bombs.
- **Atomic File Writes**: Exports write to `.tmp` files first, renaming them into place atomically to prevent partial writes. The exporter relativizes paths in JSON output to prevent leaking username paths.

---

## Output Formats & Data Payloads

- **Markdown (`.md`)**: Raw transcription retaining headings, Markdown pipe tables, list hierarchies, and LaTeX inline equations.
- **Word Document (`.docx`)**: Generated via `core/docx_export.py` using OOXML styling. Tables include repeating header rows (`w:tblHeader`) and row-split prevention (`w:cantSplit`). Document styles map headings to native Word levels (`Heading 1–3`), and page breaks are inserted strictly between non-empty scanned pages.
- **Structured JSON (`.json`)**: Contains complete processing metadata matching `OCRResult.to_dict()`:
  ```json
  {
    "file_path": "sample.pdf",
    "status": "SUCCESS",
    "total_duration": 5.4,
    "error": null,
    "aborted": false,
    "cancelled": false,
    "page_count": 2,
    "pages": [
      {
        "page_num": 1,
        "status": "SUCCESS",
        "latency": 2.7,
        "markdown": "# Transcribed Heading\n\nContent...",
        "error": null,
        "raw_json": null,
        "truncated": false
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
- **Currency Symbol Delimiter Formatting (`$DIGIT`)**:
  Standard unspaced amounts (e.g., `$100.00`, `$1,250.00`) transcribe accurately in body text, tables, and receipts. However, in documents with inline formulas or math environments, GLM-OCR's tokenizer may interpret `$` as an inline LaTeX math delimiter, which can occasionally produce token-spaced formatting like `$ 1 0 0 . 0 0`. Financial workflows with mixed formula environments should verify formula and currency spacing in exported documents.
- **Page-Boundary Cancellation**: Active HTTP vision requests cannot be safely terminated mid-transfer without destroying the underlying HTTP connection pool. Cancelling multi-page jobs completes the current in-flight page before gracefully halting.

---

## Logging Architecture & Runtime Diagnostics

### Application File Logging
When running as a packaged desktop application, runtime logs are written directly to disk:
- **Destination**: `%LOCALAPPDATA%\AksaraSight\logs\app.log`
- **Log Level Routing**: The root logger is initialized at `INFO` to record operational lifecycle events. To capture diagnostic troubleshooting details without polluting logs with high-volume third-party library noise (such as `urllib3` or `PIL`), `DEBUG` logging is specifically enabled for internal application namespaces (`web` and `core`). Unhandled crashes are intercepted via `sys.excepthook` and recorded with full tracebacks.
- **Log Rotation Policy**: Log file growth is bounded using a `RotatingFileHandler` configured with a 5 MB maximum file size (`maxBytes=5242880`) and up to 3 backup archives (`backupCount=3`, preserving `app.log.1`, `app.log.2`, and `app.log.3`).
- **Multi-Instance Concurrency on Windows**: Windows enforces mandatory file locks on open file handles. When two application instances run concurrently and share the same log file, log rotation cannot rename active log files (`PermissionError`). Python's logging handler catches this condition internally, deferring rotation until the secondary process releases its handle. Standard single-instance execution rotates logs cleanly without interruption.

### Hardware Pre-Flight & Cold-Start Diagnostics
GLM-OCR inference under the default 8,192 token context window (`-c 8192 --parallel 1`) requires approximately 2.2 GB of GPU VRAM. AksaraSight implements early hardware pre-flight checks to alert users before inference begins:
- **Asynchronous Hardware Pre-Warming**: Both the CLI (`cli/main.py`) and Web UI (`web/app.py`) invoke `start_hardware_prewarm()` on cold start. This initializes hardware detection (querying `nvidia-smi` and Vulkan physical devices) on a background daemon thread, populating an in-memory cache without delaying application startup or blocking UI rendering.
- **Low-VRAM Pre-Flight Warning**: When an NVIDIA GPU is detected with less than 2,200 MB of dedicated VRAM, an advisory warning is logged alerting the user that the server may experience CUDA out-of-memory errors or require partial CPU offloading. By checking cached profiles during server startup without acquiring blocking locks, the warning evaluates immediately without freezing process supervision.
- **Diagnostic Recommendations (`--doctor`, `--detect-hardware`)**: Comprehensive system health diagnostics recommend >= 3,000 MB dedicated VRAM to guarantee headroom for OS display compositing. Values between 2,200 MB and 3,000 MB log a non-blocking advisory note while permitting normal server startup.

---

## Testing, Build Verification & Portable Packaging

### Running the Test Suite
The test suite is configured via `pytest.ini` (`testpaths = tests`). All tests are headless unit, functional, and integration tests covering document ingestion, formatting, hardware detection, model client, Web API routes, and runtime supervision. Runs identically on both Linux and Windows.

Run tests from the repository root:

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

### Code Style & Linting
CI lints the codebase with Ruff (`ruff check .`). No static type checker is configured or run.

### Build Verification Scripts
For standalone binary distributions created with `scripts/build_portable.py`:
- `python scripts/verify_frozen_build.py`: Validates CLI version output, offline hardware detection, input error handling, Web UI desktop server startup and HTTP endpoints, and file logging in `%LOCALAPPDATA%\AksaraSight\logs\app.log`.
- `python scripts/verify_frozen_docx.py`: Asserts OOXML table structure, `_internal` asset bundling, and performs a 100% AST parity diff between source and frozen DOCX exports.

### Compiling Standalone Portable Distribution
To bundle the application into a standalone Windows x64 distribution:
```powershell
# 1. Build React frontend production bundle
cd frontend && npm ci && npm run build && cd ..

# 2. Package standalone Windows distribution
pip install -r requirements-build.txt
python scripts/build_portable.py
```
This produces `dist/AksaraSight-v<version>-windows-x64.zip` containing `AksaraSight.exe`, `AksaraSight-CLI.exe`, and the `_internal/` runtime directory.
