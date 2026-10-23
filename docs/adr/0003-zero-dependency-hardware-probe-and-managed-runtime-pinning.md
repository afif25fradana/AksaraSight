# ADR-0003: Zero-Dependency Hardware Probe and Managed Runtime Pinning

## Status
Accepted

## Date
2026-10-18

## Context
Running local LLM inference requires hardware acceleration (NVIDIA CUDA, Vulkan, or CPU fallback). Most users lack the technical background to install CUDA toolkits, identify graphics drivers, or compile binaries. Manually directing users to upstream GitHub releases creates supply-chain vulnerability and configuration mismatches. Bundling all platform binaries inside the installer would bloat the portable download from 52 MB to over 1.5 GB.

## Decision
1. Implement a zero-dependency, zero-network hardware probe (`core/hardware.py`) using `ctypes` (`nvcuda.dll`, `vulkan-1.dll`) and `nvidia-smi` to detect hardware and recommend the optimal backend (`cuda`, `vulkan`, or `cpu`).
2. Provide a managed runtime manager (`core/runtime_manager.py`) that downloads a pinned upstream build (`b11361`), verifies authoritative SHA-256 digests before extraction (fail-closed), checks against zip-slip directory traversal, and installs to `%LOCALAPPDATA%\AksaraSight\runtimes\`.
3. Provide a model weight manager (`core/model_manager.py`) that downloads pinned GLM-OCR GGUF weights (commit `65a42de1148dbed2297e922b5dbc7d9b70c36578`) with chunked SHA-256 verification.
4. Contain child server processes inside Win32 Job Objects configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` to prevent orphaned background processes.

## Alternatives Considered & Rejected
- **Bundling All Runtimes into Installer**: Rejected because distribution size would balloon to >1.5 GB, whereas base portable zip is ~52 MB.
- **Downloading `latest` Upstream Release**: Rejected because unpinned upstream updates frequently alter command-line arguments or model compatibility, breaking stability without verification.
- **`llama-cpp-python` pip package**: Rejected because pre-built Windows CUDA wheels are frequently unavailable or incompatible with newer Python releases, requiring Visual Studio C++ build tools.

## Consequences
- Base application download stays small (~52 MB).
- GPU acceleration is configured automatically without requiring CUDA SDK installations.
- All downloads are cryptographically verified before execution, eliminating supply-chain tampering risks.
- Child processes terminate reliably even if the parent application crashes.
