# ADR-0001: Decoupled Local Inference, Managed Runtimes, and Subprocess Supervision

## Status
Accepted

## Date
2026-11-13

## Context
AksaraSight executes vision-language OCR using GLM-OCR (~0.9B parameters) locally across Windows 10/11 x64 and Linux x86_64 (native desktop distributions and WSL2 environments) under Python 3.12 and 3.14. Executing local inference within a desktop client poses several architectural constraints:
1. **In-Process Dependency Overhead**: Deep learning frameworks (PyTorch, Hugging Face Transformers) have massive disk footprints (>3–5 GB), slow cold-start times (>15s), lack timely pre-built wheels for new Python releases (such as Python 3.14 on Windows), and create severe DLL dependency conflicts.
2. **Crash Resilience**: Direct C/C++ Python bindings (`ctypes` or `pybind11` directly to `llama.cpp`) expose the host process to unhandled memory faults or C++ segmentation faults that crash the entire Python desktop application without recovery.
3. **Distribution Size vs. User Setup**: Bundling all platform binaries (CUDA, Vulkan, CPU) inside the installer bloats distribution packages from ~52 MB to over 1.5 GB. Directing end users to manual upstream GitHub downloads introduces supply-chain tampering risks and configuration mismatches.
4. **Hardware Acceleration Heterogeneity**: Achieving accelerated inference requires detecting host GPU capabilities (NVIDIA CUDA, Vulkan, CPU fallback) across diverse environments without relying on uninstalled external utilities (`lspci`, `lshw`, `dmidecode`) or elevated root permissions.
5. **Process Containment**: Child inference servers risk becoming orphaned background processes if the parent application crashes or is terminated abruptly. Additionally, calling `preexec_fn=os.setpgrp` on POSIX systems is unsafe in multi-threaded Python runtimes due to memory allocator fork deadlocks.
6. **Platform Acceleration Realities**: Windows NVIDIA CUDA driver probing is vulnerable to DLL search-order preloading if unanchored. On Linux, prebuilt CUDA binaries dynamically link against distribution-specific libraries (`libcudart.so`, `libcublas.so`), resulting in widespread runtime incompatibilities across different Linux distributions.

## Decision
1. **Decoupled Out-of-Process Inference via HTTP**:
   - Isolate model execution outside the Python application process. AksaraSight acts strictly as a client, rasterizer, and workflow coordinator.
   - Inference is delegated to an external, local inference server (`llama-server` from `llama.cpp`, Ollama, or vLLM) communicating over the standard OpenAI-compatible `/v1/chat/completions` HTTP protocol with multimodal base64 JPEG data URLs over loopback.
2. **Zero-Dependency Hardware Probing (`core/hardware.py`)**:
   - Query host hardware safely without external tool dependencies:
     - **Windows**: Use Win32 `ctypes` (`nvcuda.dll`, `vulkan-1.dll`) and `nvidia-smi` to detect hardware and recommend the optimal backend (`cuda`, `vulkan`, or `cpu`). Pin NVIDIA CUDA driver DLL loading to `%SystemRoot%\System32\nvcuda.dll` to prevent DLL search-order preloading vulnerabilities.
     - **Linux**: Probe CPU via standard library `platform.processor()` and `platform.machine()`. Query `_probe_nvidia_smi()` if `nvidia-smi` is on PATH; otherwise, inspect zero-subprocess DRM sysfs (`/sys/class/drm/card*/device/vendor`) matching PCI vendor IDs (`0x10de` NVIDIA, `0x1002` AMD, `0x8086` Intel). Detect WSL2 via `/proc/version` or environment variables (`$WSL_DISTRO_NAME`, `$WSL_INTEROP`).
3. **Managed Upstream Runtime Pinning & Weight Verification**:
   - **Runtime Manager (`core/runtime_manager.py`)**: Download pinned upstream `llama.cpp` builds (`b11361`). Verify authoritative SHA-256 digests fail-closed before extraction, guard against archive traversal, and install into platform-standard data directories (`%LOCALAPPDATA%\AksaraSight\runtimes\` on Windows, `$XDG_DATA_HOME/aksarasight/` on Linux).
   - **Runtime Path Decoupling**: Dynamically resolve the active `llama-server` binary via `core.runtime_manager.resolve_effective_server_path(settings)`, keeping `config/settings.py` focused on configuration data.
   - **Dynamic Linker Prepending**: Prepend runtime binary directories to `LD_LIBRARY_PATH` during managed execution and validation on Linux, sanitizing against empty segments, trailing colons, and relative paths.
   - **Model Manager (`core/model_manager.py`)**: Download pinned GLM-OCR GGUF weights (commit `65a42de1148dbed2297e922b5dbc7d9b70c36578`) with chunked SHA-256 verification.
4. **OS Process Tree Containment & Clean Supervision (`core/server_manager.py`)**:
   - **Windows**: Bind child server processes to Win32 Job Objects configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, ensuring child processes terminate automatically if the parent process exits.
   - **Linux / POSIX**: Launch managed processes with `start_new_session=True` (creating a new POSIX process session and process group without `preexec_fn`, eliminating fork deadlock vulnerabilities). On termination, verify `proc.poll() is None` and ensure `pgid > 1` before signaling `os.killpg(pgid, signal.SIGTERM)`, escalating to `SIGKILL` if the process group does not terminate within the deadline.
   - **Handle & Stream Cleanup**: In `ServerManager.stop()`, explicitly close child stream pipes (`proc.stdout`, `proc.stderr`) and release Windows Job Object handles to prevent OS handle leaks.
5. **Dual-OS Acceleration Strategy**:
   - **Windows**: Recommend and manage CUDA runtime packages where supported.
   - **Linux**: Adopt a Vulkan-first acceleration strategy (`llama-b<build>-bin-ubuntu-vulkan-x64.tar.gz`), dynamically linking to the host's `libvulkan.so.1` driver interface without external CUDA toolkit requirements. Defer managed Linux CUDA packages due to upstream dynamic linking incompatibilities across host distributions; power users can compile native CUDA binaries and configure them via `runtime_mode="custom"` (`OCR_LLAMA_SERVER_PATH`).

## Alternatives Considered & Rejected
- **In-process PyTorch / Hugging Face Transformers**: Rejected due to massive dependency sizes (>3–5 GB), slow cold-start times (>15s), and frequent compilation or wheel failures on Windows Python 3.14.
- **Direct C/C++ Python Bindings (ctypes / pybind11 directly to llama.cpp)**: Rejected because native memory errors or C++ segmentation faults would crash the entire Python application process without recovery.
- **Hosted Cloud Inference APIs (OpenAI, Zhipu, Azure)**: Rejected to preserve the core requirement: 100% local operation with zero cloud routing of sensitive user documents.
- **Bundling All Platform Runtimes into Installer**: Rejected because distribution size would balloon to >1.5 GB, whereas base portable packages remain ~52 MB.
- **Downloading `latest` Upstream Release**: Rejected because unpinned upstream updates frequently alter command-line flags or model compatibility, breaking stability without verification.
- **`llama-cpp-python` pip package**: Rejected because pre-built Windows CUDA wheels are frequently unavailable or incompatible with newer Python releases, requiring Visual Studio C++ build tools.
- **Parsing `lshw` / `lspci` on Linux**: Rejected because external utilities require root/sudo or are missing on minimal distros, whereas DRM sysfs is zero-overhead and dependency-free.
- **Using `preexec_fn=os.setpgrp` on POSIX**: Rejected because invoking non-reentrant functions between fork and exec in multi-threaded Python runtimes risks fatal memory allocator deadlocks; `start_new_session=True` provides clean POSIX session detachment natively.
- **Bundling Linux CUDA Binaries**: Rejected due to glibc and CUDA driver library incompatibility matrices across Linux distributions.

## Consequences
- The Python desktop application remains lightweight (~52 MB) with minimal dependencies.
- Inference engine crashes or GPU out-of-memory errors are isolated from the application, returning clean HTTP error codes instead of unhandled process termination.
- All downloads are cryptographically verified before execution, eliminating supply-chain tampering risks.
- Child server processes terminate reliably across Windows and Linux without orphaned background processes.
- Hardware detection runs without external dependencies and works in headless and container environments.
- Managed Linux acceleration is stable across NVIDIA, AMD, and Intel GPUs via Vulkan without driver-toolkit mismatches.
- Requires local network loopback communication and process lifecycle supervision (`core/server_manager.py`).
