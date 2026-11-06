# ADR-0013: Linux x86_64 Platform Support and Architecture Parity

## Status
Accepted

## Date
2026-11-05

## Context
AksaraSight was originally designed and deployed for Windows 10/11 x64, with deep Windows platform integration (Job Objects for tree-wide process containment, `%LOCALAPPDATA%` filesystem hierarchy, Windows Registry and PowerShell shell bridges, and DirectML/Vulkan/CUDA binary distributions).

To extend first-class support to Linux x86_64 (including native desktop distributions like Ubuntu, Debian, Fedora, Arch, and WSL2 environments), the architecture must achieve parity without introducing bloated dependencies, shell injection vulnerabilities, or fragile platform assumptions:

1. **Hardware Probing Without Subprocesses**: Hardware detection on Windows utilized WMI/CIM or safe Win32 queries. On Linux, tools like `lspci`, `lshw`, `dmidecode`, or `inxi` are often uninstalled by default, require root/sudo privileges, or incur heavy fork/exec process overhead.
2. **Filesystem Hierarchy & Standard Directories**: Windows uses `%LOCALAPPDATA%` and `%APPDATA%`. Linux standards require adherence to the XDG Base Directory Specification (`$XDG_STATE_HOME`, `$XDG_CACHE_HOME`, `$XDG_CONFIG_HOME`).
3. **Archive Packaging & Extraction Security**: Upstream `ggml-org/llama.cpp` distributes Linux releases as `.tar.gz` tarballs rather than `.zip` files. Tar extraction is notoriously vulnerable to Tar-Slip path traversal attacks and malicious symlinks that point outside the destination directory. Furthermore, upstream Linux archives nest files inside a versioned top-level directory (`llama-b<build>/`), requiring extraction unnesting.
4. **Subprocess Lifecycle & Process Group Containment**: On Windows, child processes are bound to Windows Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) to prevent orphaned `llama-server` instances. Linux has no native Job Object API; naive `Popen.terminate()` only kills the parent shell or wrapper, leaving spawned sub-processes orphaned. Using `preexec_fn=os.setpgrp` is strictly discouraged in multi-threaded Python applications due to memory allocator fork deadlocks.
5. **NVIDIA CUDA Ecosystem Heterogeneity on Linux**: Upstream `llama.cpp` prebuilt CUDA binaries dynamically link against specific CUDA runtime libraries (`libcudart.so`, `libcublas.so`) that vary across Linux distributions. WSL2, Debian, Arch, and Fedora manage CUDA differently.

## Decision

1. **Linux Hardware Probing (`core/hardware.py`)**:
   - Query hardware metadata reliably across Linux distributions:
     - CPU: Use Python stdlib `platform.processor()` and `platform.machine()`.
     - GPU & DRM: Query `_probe_nvidia_smi()` first when `nvidia-smi` is available on PATH. Otherwise, inspect zero-subprocess DRM sysfs (`/sys/class/drm/card*/device/vendor`) matching PCI vendor IDs against known identifiers (`0x10de` NVIDIA, `0x1002` AMD, `0x8086` Intel).
     - WSL Detection: Read `/proc/version` looking for `microsoft` or check `$WSL_DISTRO_NAME` / `$WSL_INTEROP`.
   - Baseline hardware detection operates without mandatory external tools, working in restricted container or non-root environments.

2. **Strict XDG Base Directory Compliance (`core/model_manager.py`, `core/runtime_manager.py`, `config/settings.py`, `web/__main__.py`, `web/app.py`)**:
   - State and logs: Write application logs to `$XDG_STATE_HOME/aksarasight/logs/app.log` (defaulting to `~/.local/state/aksarasight/logs/app.log`).
   - Models and runtimes storage: Store downloaded models and managed runtimes in `$XDG_DATA_HOME/aksarasight/` (defaulting to `~/.local/share/aksarasight/`).
   - Configuration persistence: In frozen/portable execution where the binary directory is read-only (e.g. `/opt` or immutable mount), store settings in `$XDG_CONFIG_HOME/aksarasight/settings.env` (defaulting to `~/.config/aksarasight/settings.env`). When executable directory is writable, retain portable adjacent `.env`.
   - Security permissions: Enforce `0o600` on persisted settings files (`settings.env`) containing sensitive configurations and `0o700` on `web_uploads` temporary scratch directories; standard data directories follow user umask.

3. **Safe Tar Extraction with Path and Symlink Quarantine (`core/runtime_manager.py`)**:
   - Implement `safe_extract_tar` to extract upstream `.tar.gz` release archives.
   - Guard against Tar-Slip: Reject any archive member whose resolved path does not remain strictly within the target extraction directory.
   - Relative symlink safety: Reject absolute symlinks (`/etc/passwd`) or relative symlinks that escape the target extraction root. Unlink pre-existing symlinks in destination before regular file extraction.
   - Top-level unnesting: Automatically detect and strip wrapper parent directories (`llama-b<build>/`) to normalize runtime layouts adjacent to `llama-server`.
   - File mode preservation: Ensure extracted executable binaries (`llama-server`) and shared libraries have `0o755` permissions.

4. **POSIX Process Group Containment Without `preexec_fn` (`core/server_manager.py`)**:
   - Launch managed `llama-server` processes with `start_new_session=True` on POSIX platforms. This creates a new POSIX process session and process group with PGID equal to the child PID without invoking `preexec_fn`, eliminating fork deadlock vulnerabilities.
   - On server termination, check `proc.poll() is None` and ensure `pgid > 1` before signaling the process group via `os.killpg(pgid, signal.SIGTERM)`.
   - If the process group does not terminate within the shutdown deadline, follow up with `SIGKILL` across the entire process group (`pgid > 1`).

5. **Pragmatic CUDA Deferral & Vulkan-First Acceleration on Linux**:
   - Defer managed Linux CUDA downloads due to upstream dynamic linking incompatibilities across diverse host distros.
   - On Linux systems with NVIDIA GPUs, recommend and default to the prebuilt Vulkan runtime (`llama-b<build>-bin-ubuntu-vulkan-x64.tar.gz`), which interfaces with the host's installed `libvulkan.so.1` driver interface without external CUDA toolkit requirements.
   - Allow power users to compile custom native CUDA binaries and utilize them seamlessly via `runtime_mode="custom"` (`OCR_LLAMA_SERVER_PATH`).
   - Emits structured FAIL diagnostic check with actionable remediation if managed CUDA is manually forced on Linux.

6. **Unified Dual-Platform Packaging Pipeline (`scripts/build_portable.py`, GitHub Actions)**:
   - PyInstaller packaging builds ELF binaries (`AksaraSight` and `AksaraSight-CLI`) on Linux without `.exe` suffixes and without Windows `.ico` assets.
   - On Windows, bundles produce `.zip` archives (`AksaraSight-v<version>-windows-x64.zip`); on Linux, packaging produces `.tar.gz` archives (`AksaraSight-v<version>-linux-x64.tar.gz`) rooted at `AksaraSight/` preserving `0o755` executable bits and normalizing root ownership (`uid=0, gid=0`).
   - Both Windows and Linux CI workflows enforce full test execution with `--cov-fail-under=89`.

7. **Dynamic Linker (`LD_LIBRARY_PATH`) Prepending (`core/server_manager.py`, `core/runtime_manager.py`)**:
   - Prepend runtime binary directories to `LD_LIBRARY_PATH` during managed process execution and post-install binary validation, enabling runtime shared libraries (`libllama.so`, `libggml.so`) to resolve without system-wide installation.
   - Sanitize `LD_LIBRARY_PATH` against empty segments, trailing colons, whitespace, and relative paths to prevent untrusted library preloading.

8. **Linux Desktop Integration & WSL Browser Bridging (`web/app.py`, `web/__main__.py`)**:
   - Native file chooser: Query `zenity` (or fallback `kdialog`) for file picking when running on Linux desktop environments.
   - Directory reveal: Route file reveal through `xdg-open` targeting parent directory of files with returncode validation.
   - WSL browser bridge: In headless WSL environments without active X11/Wayland display, route browser launch via `wslview -- <url>` or `powershell.exe Start-Process '<safe_url>'` with single-quote escaping and URL scheme validation.

9. **Host Dynamic Library Diagnostic Verification (`core/diagnostics.py`)**:
   - Perform non-fatal dynamic linker probing via `ctypes.CDLL` for critical host shared libraries (`libgomp.so.1`, `libvulkan.so.1`) on Linux.
   - Emit actionable package manager remediation instructions (`apt install libgomp1 libvulkan1`) if required runtime acceleration dependencies are missing.


## Consequences

- Full feature parity across Windows x64 and Linux x86_64, including WSL2.
- Zero external runtime dependencies added; hardware detection is instant, dependency-free, and safe in headless/container environments.
- Process tree containment on Linux is leak-proof and avoids Python fork deadlocks.
- Upstream archive extraction is secure against Tar-Slip and symlink escape vulnerabilities.
- Managed Linux acceleration is stable across all NVIDIA/AMD/Intel GPUs via Vulkan without driver-toolkit mismatches.
