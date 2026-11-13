# ADR-0003: Presentation Architecture: Web UI Workspace and Accessibility

## Status
Accepted

## Date
2026-11-13

## Context
AksaraSight previously utilized a native desktop GUI built on Tkinter, CustomTkinter, and TkinterDnD2 (`gui/`). This implementation encountered several limitations:
1. **Tcl Threading & Garbage Collection Deadlocks**: The native Tcl/Tk interpreter suffered from intermittent font garbage collection deadlocks (`Font.__del__` race conditions) during rapid window redraws.
2. **Headless Linux CI Incompatibility**: CustomTkinter cannot initialize without a running display server (X11 or Wayland), forcing GUI test suites to be disabled or skipped on Linux CI.
3. **High-DPI Layout Clipping**: Standard 1080p laptop displays at 125% DPI scaling caused severe layout clipping and control overlap during half-screen snapping under Windows.
4. **Brittle Polling Architecture**: The UI relied on periodic polling timers rather than reactive streaming events.
5. **Model Lifecycle UI Latency**: Background model downloads lacked terminal Server-Sent Events (SSE), leaving the UI in a stale "No Local Model" state until manual refresh.
6. **CSS View Transitions API Collisions**: Applying the native View Transitions API (`document.startViewTransition`) to nested layout containers decoupled them from the root snapshot, clipping full-viewport theme transitions (such as the circular ripple animation).
7. **Accessibility (WCAG 2.1 AA) Deficits**: Modal dialogs lacked focus containment, initial focus targeting, and focus restoration upon exit (WCAG 2.1.2 & 2.4.3). Exported file lists were non-interactive to keyboard users (WCAG 2.1.1). On narrow viewports (< 1024px), single-column layouts clipped content below the fold.

## Decision
1. **Retirement of Native GUI & Adoption of Web Workspace**:
   - Retire the native desktop GUI from `main` (permanently frozen at `v1.2.1` on branch `release/1.2`) and replace it with a browser-based local Web UI workspace (`web/` and `frontend/`).
   - The backend is served via FastAPI and Uvicorn on loopback (`127.0.0.1:8000`), pushing real-time progress to a React 19 Single Page Application via Server-Sent Events (SSE).
   - The packaged portable desktop executable (`AksaraSight.exe` / `AksaraSight`) starts the local server and automatically launches the user's default browser.
2. **CSS View Transitions Isolation Boundary**:
   - Reserve the native View Transitions API exclusively for document-wide, full-viewport transformations (the circular ripple theme transition).
   - Prohibit assigning explicit `view-transition-name` to inner layout containers. Sub-view transitions (Workspace ↔ Settings) use standard CSS transitions (`animate-fade-in`) to maintain a monolithic DOM root for full-screen view transitions.
3. **Zero-Dependency Native Accessibility (WCAG 2.1 AA)**:
   - Implement a lightweight, zero-dependency `useFocusTrap` hook (`frontend/src/hooks/useFocusTrap.ts`) utilizing React refs and standard DOM event listeners. Caches `document.activeElement` prior to opening to restore focus on unmount; traps `Tab` / `Shift+Tab` within the modal container.
   - Provide semantic keyboard controls (`role="button"`, `tabIndex={0}`, `aria-pressed`, `onKeyDown` Enter/Space) on exported file items in modals.
4. **Responsive Viewport Overflow Resilience**:
   - Configure `<main>` in `frontend/src/App.tsx` with `overflow-y-auto lg:overflow-hidden` and provide minimum panel heights (`min-h-[340px]`, `min-h-[460px] lg:h-full`), enabling smooth vertical scrolling on mobile/tablet viewports while preserving fixed 3-column height on desktop displays.
5. **Discrete Parameter Controls & Real-Time SSE Synchronization**:
   - Replace continuous range sliders with structured 2x2 interactive Card Buttons (72, 100, 150, 200 DPI) incorporating semantic `aria-pressed`, tactile depress feedback, and descriptive copy.
   - Emit an explicit terminal SSE payload (`model_download_progress` with `status: "completed"`) from the backend downloader thread, triggering immediate UI state refetch without manual page reload.
   - Synchronize workspace extraction DPI and global settings bidirectionally (`PATCH /api/settings`).
6. **Cross-Platform Desktop Integration**:
   - **File Chooser**: Win32 FileDialog on Windows; `zenity` (or fallback `kdialog`) on Linux desktop.
   - **Directory Reveal**: Windows Explorer on Windows; `xdg-open` on Linux with returncode validation.
   - **WSL Browser Bridging**: In headless WSL environments, route browser launches via `wslview -- <url>` or `powershell.exe Start-Process '<safe_url>'` with single-quote escaping and URL scheme validation.

## Alternatives Considered & Rejected
- **PySide6 / PyQt6**: Rejected due to heavy distribution size (>150 MB binary overhead), complex LGPL licensing, and continued display server requirements in headless CI.
- **CustomTkinter Refactoring via Controller/Mediator**: Rejected because code refactoring could not resolve underlying platform limitations (Tcl threading deadlocks, Linux CI display requirements, DPI scaling glitches).
- **Electron Application Wrapper**: Rejected due to excessive memory footprint (>300 MB idle RAM) and bundle bloat (>120 MB Chromium wrapper).
- **Third-Party Focus Trap Libraries (`focus-trap-react`, `react-focus-lock`)**: Rejected because they add ~15–30 KB to bundle size, introduce transitive dependencies, and trigger React 19 peer-dependency warnings. Standard DOM querySelector and keydown listeners solve the problem with zero dependencies in < 80 lines of TypeScript.
- **Nested Multi-Group View Transitions**: Rejected because browser View Transitions API isolates named groups from the root snapshot, breaking unified full-viewport clip-path transitions.
- **Continuous DPI Slider (50–600 DPI)**: Rejected because unconstrained raster resolutions cause erratic memory consumption, cache invalidation, and unpredictable vision LLM inference times.

## Consequences
- Test suites run 100% headless across Windows and Linux CI without display server emulators (Xvfb).
- Rich, responsive UI with side-by-side document preview, full-text rendering, theme switching, and real-time SSE progress updates.
- All modal dialogs comply with WCAG 2.1 AA requirements for keyboard navigation, focus containment, and focus restoration.
- Mobile and tablet viewports scroll cleanly through all workspace panels without content truncation.
- Full-screen circular ripple theme transitions render smoothly without clipping or frame tearing.
- Provides desktop integration across Windows, Linux, and WSL2.
- Requires network security middleware (`web/security.py`) to prevent cross-site request attacks.
- Requires building frontend production bundles (`npm run build`) before packaging releases.
