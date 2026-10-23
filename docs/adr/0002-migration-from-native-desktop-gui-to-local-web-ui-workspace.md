# ADR-0002: Migration from Native Desktop GUI to Local Web UI Workspace

## Status
Accepted

## Date
2026-10-18

## Context
AksaraSight previously used a native desktop GUI built on Tkinter, CustomTkinter, and TkinterDnD2 (`gui/`). This implementation accumulated severe technical debt:
1. Native Tcl interpreter garbage-collection deadlocks (`Font.__del__` race conditions).
2. Headless Linux CI incompatibility: CustomTkinter cannot initialize without a display server, forcing GUI tests to be skipped on Linux CI.
3. Windows laptop display scaling issues: At 125% DPI scaling (standard on 1080p laptops), window constraints clipped controls during half-screen snapping.
4. Brittle GUI thread event loops relying on periodic polling timers.

## Decision
Retire the native desktop GUI from `main` (permanently frozen at `v1.2.1` on branch `release/1.2`) and replace it with a browser-based local Web UI workspace (`web/` and `frontend/`). The backend is served via FastAPI and Uvicorn on loopback (`127.0.0.1:8000`), pushing real-time progress to a React 19 Single Page Application via Server-Sent Events (SSE). The packaged desktop application (`AksaraSight.exe`) starts the local server and automatically opens the user's default browser.

## Alternatives Considered & Rejected
- **PySide6 / PyQt6**: Rejected due to heavy distribution size (>150 MB binary overhead), complex licensing (LGPL/Commercial), and continued display server requirements in headless CI.
- **CustomTkinter Refactoring via Controller/Mediator**: Rejected because code refactoring could not solve underlying platform flaws (Tcl threading limitations, Linux CI display requirements, DPI scaling glitches).
- **Electron Application Wrapper**: Rejected due to excessive memory footprint (>300 MB idle RAM) and bundle bloat (>120 MB Chromium wrapper).

## Consequences
- Test suites run 100% headless across Windows and Linux CI without display server emulators (Xvfb).
- Rich, responsive UI with side-by-side document preview, full-text rendering, theme switching, and real-time SSE progress updates.
- The desktop launcher (`AksaraSight.exe`) remains a portable executable that auto-launches the system browser.
- Requires network security middleware (`web/security.py`) to prevent cross-site request attacks.
