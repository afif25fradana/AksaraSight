# Contributing to AksaraSight

Thank you for your interest in contributing to AksaraSight! AksaraSight is a personal open-source project designed for private, offline-first OCR running entirely on local consumer hardware.

To keep the application stable, reliable, and respectful of user privacy, please review this guide before submitting changes.

---

## Core Invariants

Any contribution must adhere to these non-negotiable architectural principles:

1. **Strictly Offline-First**: No background analytics, telemetry, or remote cloud fallbacks. Processing must halt with a clean error if local backends are unavailable.
2. **Loopback Network Isolation**: Web API routes and client network sessions must strictly bind to loopback (`127.0.0.1` / `localhost`) and reject external origins unless explicitly permitted by `--allow-remote`.
3. **Thread Safety for PDFium**: `pypdfium2` bindings are not thread-safe. All document rendering and page probing must go through `_PDFIUM_LOCK` in `core/pipeline.py`.
4. **Clean Root Invariant**: Documentation and community files belong in their designated directories (`docs/`, `.github/`, `scripts/`). Do not add arbitrary config files to the repository root.

---

## Local Development Setup

### Prerequisites
- Python 3.12+ (tested on Python 3.12 and 3.14).
- Node.js 22+ (for frontend development).
- Standard [Microsoft Visual C++ 2015–2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) on Windows.

### 1. Backend Setup
```powershell
git clone https://github.com/afif25fradana/AksaraSight
cd AksaraSight

python -m venv .venv
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux / macOS:
# source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Frontend Setup
```powershell
cd frontend
npm install
cd ..
```

---

## Local Verification Commands

Before opening a pull request, verify all local checks pass cleanly:

### 1. Python Test Suite & Linter
```powershell
# Run backend test suite (unit, functional, integration)
python -m pytest

# Check code formatting and linting
ruff check .
```

### 2. Frontend Test Suite & Typecheck
```powershell
cd frontend

# Run TypeScript compiler check
npm run lint

# Run Vitest suite
npm test
```

### 3. Frontend Build & Static Bundle Synchronization
AksaraSight distributes a pre-compiled React Single Page Application in `web/static/`. If you modify any file in `frontend/src/`, you must rebuild the bundle before submitting your PR:

```powershell
cd frontend
npm run build
cd ..
```

CI will fail if `frontend/src/` changes are committed without the updated bundle in `web/static/`.

---

## Pull Request Guidelines

1. **Atomic & Focused**: Keep PRs focused on a single bug fix or feature.
2. **Include Tests**: Add corresponding test coverage under `tests/` for backend changes, or `frontend/src/test/` for Web UI changes.
3. **Document Decisions**: If introducing architectural shifts or new invariant patterns, consider adding an Architecture Decision Record under `docs/adr/`.
4. **Verify CI**: All GitHub Actions checks (`test-windows`, `test-linux`, and `lint`) must pass.
