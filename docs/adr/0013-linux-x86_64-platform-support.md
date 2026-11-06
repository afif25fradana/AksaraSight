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

1. **Zero-Subprocess sysfs/procfs/DRM Hardware Probes (`core/hardware.py`)**:
   - Query hardware metadata purely through Linux kernel virtual filesystems (`/proc` and `/sys`):
     - CPU: Parse `/proc/cpuinfo` for model name and core flags (`avx`, `avx2`, `neon`).
     - RAM: Read `/proc/meminfo` (`MemTotal`).
     - GPU & DRM: Inspect `/sys/class/drm/card*/device/vendor` and `device` sysfs nodes. Match PCI vendor IDs against known identifiers (`0x10de` NVIDIA, `0x1002` AMD, `0x8086` Intel).
     - WSL Detection: Read `/proc/version` looking for `microsoft` or check `$WSL_DISTRO_NAME` / `$WSL_INTEROP`.
   - Zero external subprocesses are spawned for baseline hardware detection, guaranteeing instant, zero-fork detection that works in restricted container or non-root environments.

2. **Strict XDG Base Directory Compliance (`core/model_manager.py`, `core/runtime_manager.py`, `config/settings.py`, `web/__main__.py`)**:
   - State and logs: Write application logs to `$XDG_STATE_HOME/aksarasight/logs/app.log` (defaulting to `~/.local/state/aksarasight/logs/app.log`).
   - Models and runtimes cache: Store downloaded models and managed runtimes in `$XDG_CACHE_HOME/aksarasight/` (defaulting to `~/.cache/aksarasight/`).
   - Configuration persistence: In frozen/portable execution where the binary directory is read-only (e.g. `/opt` or immutable mount), store settings in `$XDG_CONFIG_HOME/aksarasight/settings.env` (defaulting to `~/.config/aksarasight/settings.env`). When executable directory is writable, retain portable adjacent `.env`.
   - Security permissions: Enforce `0o600` on persisted settings files containing sensitive configurations and `0o700` on created configuration/cache directories.

3. **Safe Tar Extraction with Path and Symlink Quarantine (`core/runtime_manager.py`)**:
   - Implement `safe_extract_tar` to extract upstream `.tar.gz` release archives.
   - Guard against Tar-Slip: Reject any archive member whose resolved path does not remain strictly within the target extraction directory.
   - Relative symlink safety: Reject absolute symlinks (`/etc/passwd`) or relative symlinks that escape the target extraction root.
   - Top-level unnesting: Automatically detect and strip wrapper parent directories (`llama-b<build>/`) to normalize runtime layouts adjacent to `llama-server`.
   - File mode preservation: Ensure extracted executable binaries (`llama-server`) and shared libraries have `0o755` permissions.

4. **POSIX Process Group Containment Without `preexec_fn` (`core/server_manager.py`)**:
   - Launch managed `llama-server` processes with `start_new_session=True` on POSIX platforms. This creates a new POSIX process session and process group with PGID equal to the child PID without invoking `preexec_fn`, eliminating fork deadlock vulnerabilities.
   - On server termination, send `SIGTERM` to the entire process group via `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)`.
   - If the process group does not terminate within the shutdown deadline, follow up with `SIGKILL` across the entire process group.

5. **Pragmatic CUDA Deferral & Vulkan-First Acceleration on Linux**:
   - Defer managed Linux CUDA downloads due to upstream dynamic linking incompatibilities across diverse host distros.
   - On Linux systems with NVIDIA GPUs, recommend and default to the prebuilt Vulkan runtime (`llama-b<build>-bin-ubuntu-vulkan-x64.tar.gz`), which interfaces with the host's installed `libvulkan.so.1` driver interface without external CUDA toolkit requirements.
   - Allow power users to compile custom native CUDA binaries and utilize them seamlessly via `runtime_mode="custom"` (`OCR_LLAMA_SERVER_PATH`).
   - Emits structured FAIL diagnostic check with actionable remediation if managed CUDA is manually forced on Linux.

6. **Unified Dual-Platform Packaging Pipeline (`scripts/build_portable.py`, GitHub Actions)**:
   - PyInstaller packaging builds ELF binaries (`AksaraSight` and `AksaraSight-CLI`) on Linux without `.exe` suffixes and without Windows `.ico` assets.
   - On Windows, bundles produce `.zip` archives (`AksaraSight-v<version>-windows-x64.zip`); on Linux, packaging produces `.tar.gz` archives (`AksaraSight-v<version>-linux-x64.tar.gz`) rooted at `AksaraSight/` preserving `0o755` executable bits.
   - Both Windows and Linux CI workflows enforce full test execution with `--cov-fail-under=89`.

## Consequences

- Full feature parity across Windows x64 and Linux x86_64, including WSL2.
- Zero external runtime dependencies added; hardware detection is instant, dependency-free, and safe in headless/container environments.
- Process tree containment on Linux is leak-proof and avoids Python fork deadlocks.
- Upstream archive extraction is secure against Tar-Slip and symlink escape vulnerabilities.
- Managed Linux acceleration is stable across all NVIDIA/AMD/Intel GPUs via Vulkan without driver-toolkit mismatches.
