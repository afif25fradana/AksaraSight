# ADR-0005: Defense-in-Depth Security, Loopback Boundary, and Anti-Exfiltration

## Status
Accepted

## Date
2026-11-19

## Context
AksaraSight processes private, sensitive, and proprietary documents (financial records, legal agreements, medical documentation, identification cards). Running a local web server (FastAPI) and an inference endpoint on a user's workstation exposes the system to several attack vectors:
1. **Network Exposure & Drive-By Attacks**: Binding to external interfaces or accepting unvalidated requests enables local network snooping, DNS rebinding, and cross-site request attacks from malicious websites open in concurrent browser tabs.
2. **Proxy Interception & Data Leakage**: Workstations configured with system-wide proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`) risk routing sensitive loopback inference payloads through external corporate or third-party proxies.
3. **Archive Extraction Vulnerabilities**: Downloading upstream release archives (`.tar.gz` and `.zip`) for managed runtimes introduces Zip-Slip and Tar-Slip directory traversal risks, as well as symlink escape vulnerabilities targeting host filesystems.
4. **Filesystem Information Disclosure & Contention**: Persisted configuration files, temporary upload scratch folders, and export file operations risk disclosing local workstation usernames, directory hierarchies, or suffering Windows NTFS file-locking contention (`[WinError 32]`) during rapid application restarts.
5. **Binary & DLL Preloading Hijacks**: Unanchored dynamic library loading risks executing malicious DLLs or shared libraries placed in untrusted working directories.
6. **Subprocess Outbound Network Leakage**: Permitting local server managers to pass Hugging Face repository identifiers (`-hf <repo>`) directly to child inference processes enables unmonitored external network connections, bypassing application proxy guards and exfiltrating workstation network presence.
7. **Incomplete Download Corruption & Truncation**: Network interruptions during large multi-hundred-megabyte GGUF model downloads can lead to truncated or corrupted partial files. Resuming against corrupted offsets can yield HTTP 416 (Range Not Satisfiable), risking infinite download loops or corrupted weight execution if unhandled.

## Decision
1. **Strict Loopback Gate**:
   - `Settings` enforces that endpoints point strictly to loopback addresses (`localhost`, `127.0.0.1`, `[::1]`) unless `allow_remote=True` is explicitly configured.
   - A security confirmation modal warns users before allowing any non-loopback network connection.
2. **Security Middleware & Browser Hardening**:
   - `LoopbackSecurityMiddleware` validates `Host` headers against the bound port, rejects all cross-site requests (`Sec-Fetch-Site: cross-site`) targeting `/api/` endpoints with HTTP 403 Forbidden, and injects hardening response headers:
     - `X-Frame-Options: DENY` (clickjacking defense)
     - `X-Content-Type-Options: nosniff` (MIME sniffing defense)
     - `Content-Security-Policy: frame-ancestors 'none'; default-src 'self' 'unsafe-inline' data: blob:` (asset isolation)
3. **Proxy Interception Defense & Subprocess Sanitization**:
   - Disable environment proxies (`trust_env = False`) on all internal `requests.Session` instances (including ephemeral probe sessions in `probe_server_health`) to prevent system proxy variables from intercepting local traffic.
   - When spawning managed child processes in `core/server_manager.py`, clone `os.environ` into an isolated `sub_env`, purge all proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and lowercase variants), and explicitly enforce `sub_env["NO_PROXY"] = "*"` and `sub_env["no_proxy"] = "*"`.
4. **Safe Archive Extraction (Tar-Slip & Zip-Slip Defense)**:
   - Implement `safe_extract_tar` (`core/runtime_manager.py`) and safe zip extraction: reject any archive member whose resolved destination does not remain strictly within the target extraction root.
   - Reject absolute symlinks (e.g., `/etc/passwd`) or relative symlinks that escape the target root. Unlink pre-existing symlinks in destination prior to file extraction.
   - Automatically detect and strip top-level wrapper directories (`llama-b<build>/`) to normalize runtime layouts adjacent to `llama-server`. Ensure extracted executable binaries have `0o755` permissions.
5. **Filesystem Permissions & Advisory Locks**:
   - Enforce POSIX `0o600` on persisted settings files (`settings.env`) containing configurations and `0o700` on `web_uploads` temporary scratch directories; standard data directories follow user umask.
   - Retain the 0-byte `.instance.lock` file on disk upon shutdown, releasing only the OS kernel lock via `_release_instance_lock`. This prevents `[WinError 32]` access-denied contention and re-acquisition races during rapid application restart on Windows NTFS.
6. **Path Sanitization & Injection Defense**:
   - Pass `base_dir=target_upload_dir` to `format_output` in `export_document` to prevent username and parent directory leaks in JSON exports. Relativize file paths and sanitize error messages to avoid disclosing user account names or local filesystem hierarchies.
   - Write export files atomically via `.tmp` scratch files and `os.replace`.
   - Require `target.suffix.lower() in ALLOWED_OUTPUT_EXTS`, reject symlinks, and assert canonical directory containment in `delete_output_file`.
   - Sanitize export stems with `sanitize_filename_stem` against Windows reserved DOS device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
   - Anchor dynamic library loading strictly to authoritative paths to prevent CWE-427 DLL search order preloading/hijacking:
     - CUDA: pin Windows NVIDIA CUDA driver loading strictly to `%SystemRoot%\System32\nvcuda.dll`.
     - NVML Telemetry: enforce a dual-path anchored search order on Windows, checking `%SystemRoot%\System32\nvml.dll` followed by `%ProgramFiles%\NVIDIA Corporation\NVSMI\nvml.dll` via `os.environ.get()` with robust defaults; on Linux and WSL environments, query explicit system locations (`libnvidia-ml.so.1` and `/usr/lib/wsl/lib/libnvidia-ml.so.1`).
     - Sanitize `LD_LIBRARY_PATH` against empty segments, trailing colons, whitespace, and relative paths.
7. **Downloader Hardening & Verified Model Integrity (`core/model_manager.py`, `core/server_manager.py`)**:
   - **Mandatory Pre-Execution Hash Verification**: `ServerManager` enforces `get_local_model_paths(repo, verify_hash=True)` before spawning `llama-server`. The check computes chunked SHA-256 digests fail-closed against authoritative pinned constants for both the base model and projector.
   - **Elimination of Outbound `-hf` Fallback**: The legacy fallback that spawned `llama-server -hf <repo>` when weights were missing is removed. Missing or corrupt model files raise `FileNotFoundError` immediately, guaranteeing that child processes never initiate outbound network connections to external services.
   - **Resilient Resumption & HTTP 416 Recovery**: `ModelDownloader` supports chunked HTTP range resumption. If an HTTP 416 (Range Not Satisfiable) status is received due to an invalid byte offset or corrupted `.part` file, the downloader unlinks the `.part` file, decrements the tracked `bytes_downloaded` counter under thread lock, notifies progress listeners, and cleanly retries the transfer from byte 0 without the `Range` header.
   - **Pre-Flight Pruning of Legacy Models**: `prune_legacy_models()` purges deprecated model directories (`models/glm-ocr-q8_0/`) prior to calculating disk space requirements, preventing false out-of-disk failures during upgrades while handling Windows file locks gracefully.

## Alternatives Considered & Rejected
- **Standard CORS Headers Alone**: Rejected because CORS headers do not protect against simple requests, direct local network access, or DNS rebinding.
- **User Authentication / JWT Passwords**: Rejected as unnecessary complexity for a single-user desktop tool running locally on a personal workstation.
- **Global Proxy Disabling via OS Registry**: Rejected because application processes should not tamper with host system network settings; subprocess environment isolation guarantees local immunity without side effects.
- **Unlinking `.instance.lock` on Windows Exit**: Rejected because Windows NTFS file locking causes immediate WinError 32 contention if a new process attempts to acquire the lock before the exiting process completes handle teardown. Retaining the 0-byte lock file eliminates this race.
- **Allowing `-hf` Subprocess Fallback for Missing Models**: Rejected because passing repository IDs to child binaries allows external HTTP/HTTPS calls outside Python application oversight, violating the zero-exfiltration security boundary.
- **Ignoring HTTP 416 / Unconditional Overwrite without Reset**: Rejected because failing to reset range headers on invalid partial files causes permanent download loops or corrupt model weights.
- **Unanchored Dynamic Library Loading (`ctypes.CDLL("nvml.dll")`)**: Rejected because unanchored DLL loading follows default OS search heuristics (searching current working directory and application root first), creating CWE-427 DLL hijacking attack surfaces if malicious binaries are planted in user folders.

## Consequences
- Documents and OCR transcriptions never leave the local workstation.
- Protects the local server from browser-based drive-by attacks originating from malicious websites open in other tabs.
- Child processes are isolated from host proxy configurations and prohibited from initiating outbound network connections.
- Dynamic library loading for GPU detection and NVML telemetry is anchored to absolute system paths, mitigating CWE-427 DLL preloading.
- Runtime extraction is protected against malicious archive traversal and symlink escapes.
- Model downloads feature cryptographic SHA-256 integrity verification, safe range-resumption with HTTP 416 self-healing, and automatic legacy weight pruning.
- Sensitive configuration and upload directories are protected by strict permissions (`0o600`/`0o700`).
- Export writes and deletions are atomic and directory-confined.
- Rapid application restarts on Windows operate cleanly without lock contention.
- Non-loopback network connections require explicit user confirmation and CLI flags (`--allow-remote`).
