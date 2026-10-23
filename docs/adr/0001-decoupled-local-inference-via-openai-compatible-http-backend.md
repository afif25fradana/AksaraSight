# ADR-0001: Decoupled Local Inference via OpenAI-Compatible HTTP Backend

## Status
Accepted

## Date
2026-10-18

## Context
AksaraSight runs vision-language OCR using the GLM-OCR model (~0.9B parameters) locally on Windows 10/11 with Python 3.12 and Python 3.14. Deep learning frameworks like PyTorch and Transformers have large installation footprints (3 to 5 GB), frequently lack pre-built wheels for new Python versions (such as Python 3.14 on Windows), and suffer from DLL dependency conflicts. We need an inference architecture that keeps the Python desktop application lightweight, fast to install, and isolated from native runtime crashes.

## Decision
Isolate model execution entirely outside the Python application process. AksaraSight acts strictly as a client, rasterizer, and workflow coordinator. Inference is delegated to an external, local inference server (`llama-server` from llama.cpp, or Ollama) communicating over the standard OpenAI-compatible `/v1/chat/completions` HTTP protocol with multimodal base64 JPEG payloads.

## Alternatives Considered & Rejected
- **In-process PyTorch / Hugging Face Transformers**: Rejected due to massive dependency sizes (>3 GB), slow cold-start times (>15s), and frequent compilation or wheel failures on Windows Python 3.14.
- **Direct C/C++ Python Bindings (ctypes / pybind11 directly to llama.cpp)**: Rejected because native memory errors or C++ segmentation faults would crash the entire Python application process without recovery.
- **Hosted Cloud Inference APIs (OpenAI, Zhipu, Azure)**: Rejected outright due to the foundational project invariant: 100% local operation with zero cloud routing of sensitive user documents.

## Consequences
- The Python application remains lightweight (<55 MB package) with minimal dependencies.
- Inference engine crashes or GPU out-of-memory errors are isolated from the application, returning clean HTTP error codes instead of unhandled process termination.
- Users can switch between backends (`llama-cpp`, `ollama`, `vllm`) without modifying Python application code.
- Requires local network loopback communication and process lifecycle supervision (`core/server_manager.py`).
