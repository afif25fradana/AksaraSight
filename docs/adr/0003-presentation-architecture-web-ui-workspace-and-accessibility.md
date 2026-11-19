# ADR-0003: Presentation Architecture: Web UI Workspace and Accessibility

## Status
Accepted

## Date
2026-11-19

## Context
AksaraSight previously utilized a native desktop GUI built on Tkinter, CustomTkinter, and TkinterDnD2 (`gui/`). This implementation encountered several limitations:
1. **Tcl Threading & Garbage Collection Deadlocks**: The native Tcl/Tk interpreter suffered from intermittent font garbage collection deadlocks (`Font.__del__` race conditions) during rapid window redraws.
2. **Headless Linux CI Incompatibility**: CustomTkinter cannot initialize without a running display server (X11 or Wayland), forcing GUI test suites to be disabled or skipped on Linux CI.
3. **High-DPI Layout Clipping**: Standard 1080p laptop displays at 125% DPI scaling caused severe layout clipping and control overlap during half-screen snapping under Windows.
4. **Brittle Polling Architecture**: The UI relied on periodic polling timers rather than reactive streaming events.
5. **Model Lifecycle UI Latency**: Background model downloads lacked terminal Server-Sent Events (SSE), leaving the UI in a stale "No Local Model" state until manual refresh.
6. **CSS View Transitions API Collisions**: Applying the native View Transitions API (`document.startViewTransition`) to nested layout containers decoupled them from the root snapshot, clipping full-viewport theme transitions (such as the circular ripple animation).
7. **Accessibility (WCAG 2.1 AA) Deficits**: Modal dialogs lacked focus containment, initial focus targeting, and focus restoration upon exit (WCAG 2.1.2 & 2.4.3). Exported file lists were non-interactive to keyboard users (WCAG 2.1.1). On narrow viewports (< 1024px), single-column layouts clipped content below the fold.
8. **Browser Window Isolation & Process Lifecycle**: Launching a local Web UI inside the user's default browser tab subjects the application to third-party extensions, mixed tab clutter, and lack of standalone desktop window ergonomics. Closing the browser tab leaves the local Uvicorn and inference processes running silently in the background.
9. **Console Windowing & Startup Error Visibility**: Windows desktop executables built with console mode display an unwanted command prompt window behind the UI. Conversely, building in windowed mode (`console=False`) sets standard streams (`sys.stdin`, `sys.stdout`, `sys.stderr`) to `None`, risking runtime crashes in subprocesses or formatters, and causes early startup errors (e.g., port collisions) to fail silently without user feedback.

## Decision
1. **Retirement of Native GUI & Adoption of Web Workspace**:
   - Retire the native desktop GUI from `main` (permanently frozen at `v1.2.1` on branch `release/1.2`) and replace it with a browser-based local Web UI workspace (`web/` and `frontend/`).
   - The backend is served via FastAPI and Uvicorn on loopback (`127.0.0.1:8000`), pushing real-time progress to a React 19 Single Page Application via Server-Sent Events (SSE).
   - The packaged portable desktop executable (`AksaraSight.exe` / `AksaraSight`) starts the local server and automatically launches the user interface.
2. **Standalone Chromium/Edge App-Mode Launcher**:
   - Provide a native desktop application window via Chromium-family `--app` launcher mode (`web/__main__.py`).
   - Resolve installed Chromium executables across platforms:
     - **Windows**: Search Microsoft Edge and Google Chrome in standard 32-bit/64-bit Program Files and LocalAppData paths, with fallback to Windows Registry (`HKLM`/`HKCU` `App Paths` for `msedge.exe`, `chrome.exe`, and `brave.exe`).
     - **Linux**: Check display server availability (`DISPLAY` or `WAYLAND_DISPLAY`), then search `google-chrome`, `chromium`, `chromium-browser`, and `microsoft-edge` via `shutil.which()`.
   - Launch the window with an isolated user profile directory (`--user-data-dir` pointing to `%LOCALAPPDATA%\AksaraSight\browser_profile` on Windows, or `$XDG_STATE_HOME/aksarasight/browser_profile` / `~/.local/state/aksarasight/browser_profile` on Linux) and suppress initial setup wizards (`--no-first-run`, `--no-default-browser-check`).
   - Fall back transparently to default browser launching (`_open_browser`) if no Chromium executable is detected or if launch fails, preserving headless WSL2 bridging via `wslview` or `powershell.exe Start-Process`.
3. **Active SSE Lifecycle Supervision (`SSEShutdownSupervisor`)**:
   - Supervise connected browser sessions via `SSEShutdownSupervisor` in non-development, auto-launched server runs.
   - Increment active client counters on `/api/events` SSE connections and decrement on disconnection.
   - When active clients reach zero, initiate a 10-second debounce timer (`_debounce_shutdown`). Reconnecting within 10 seconds (e.g., page refresh via F5) cancels the pending shutdown.
   - If the debounce timer expires while the orchestrator is actively processing jobs (`orchestrator.is_busy()`), enter an `EVACUATING` state (`_evacuating = True`), polling every 0.5 seconds until in-flight document extraction completes before signaling server exit (`server.should_exit = True`).
4. **Windowed PyInstaller Build & Startup Error Boundary**:
   - Build the portable Windows desktop executable (`exe_web` in `build_portable.spec`) with `console=False`, preventing console window popups.
   - Safeguard standard stream redirection during startup (`_setup_frozen_logging()`): redirect `sys.stdin`, `sys.stdout`, and `sys.stderr` to `os.devnull` when `None`.
   - Implement a fatal GUI error boundary (`_fatal_gui_error`): on startup exceptions (such as invalid loopback hosts or port collisions), log the critical error and display a native Win32 dialog box via `ctypes.windll.user32.MessageBoxW(0, message, "AksaraSight - <Title>", 0x10)` before exiting (`sys.exit(1)`).
5. **CSS View Transitions Isolation Boundary**:
   - Reserve the native View Transitions API exclusively for document-wide, full-viewport transformations (the circular ripple theme transition).
   - Prohibit assigning explicit `view-transition-name` to inner layout containers. Sub-view transitions (Workspace ↔ Settings) use standard CSS transitions (`animate-fade-in`) to maintain a monolithic DOM root for full-screen view transitions.
6. **Zero-Dependency Native Accessibility (WCAG 2.1 AA)**:
   - Implement a lightweight, zero-dependency `useFocusTrap` hook (`frontend/src/hooks/useFocusTrap.ts`) utilizing React refs and standard DOM event listeners. Caches `document.activeElement` prior to opening to restore focus on unmount; traps `Tab` / `Shift+Tab` within the modal container.
   - Provide semantic keyboard controls (`role="button"`, `tabIndex={0}`, `aria-pressed`, `onKeyDown` Enter/Space) on exported file items in modals.
7. **Responsive Viewport Overflow Resilience**:
   - Configure `<main>` in `frontend/src/App.tsx` with `overflow-y-auto lg:overflow-hidden` and provide minimum panel heights (`min-h-[340px]`, `min-h-[460px] lg:h-full`), enabling smooth vertical scrolling on mobile/tablet viewports while preserving fixed 3-column height on desktop displays.
8. **Discrete Parameter Controls & Real-Time SSE Synchronization**:
   - Replace continuous range sliders with structured 2x2 interactive Card Buttons (72, 100, 150, 200 DPI) incorporating semantic `aria-pressed`, tactile depress feedback, and descriptive copy.
   - Emit an explicit terminal SSE payload (`model_download_progress` with `status: "completed"`) from the backend downloader thread, triggering immediate UI state refetch without manual page reload.
   - Synchronize workspace extraction DPI and global settings bidirectionally (`PATCH /api/settings`).
9. **Cross-Platform Desktop Integration**:
   - **File Chooser**: Win32 FileDialog on Windows; `zenity` (or fallback `kdialog`) on Linux desktop.
   - **Directory Reveal**: Windows Explorer on Windows; `xdg-open` on Linux with returncode validation.
   - **WSL Browser Bridging**: In headless WSL environments, route browser launches via `wslview -- <url>` or `powershell.exe Start-Process '<safe_url>'` with single-quote escaping and URL scheme validation.

## Alternatives Considered & Rejected
- **PySide6 / PyQt6**: Rejected due to heavy distribution size (>150 MB binary overhead), complex LGPL licensing, and continued display server requirements in headless CI.
- **CustomTkinter Refactoring via Controller/Mediator**: Rejected because code refactoring could not resolve underlying platform limitations (Tcl threading deadlocks, Linux CI display requirements, DPI scaling glitches).
- **Electron / WebView2 / PyWebView Application Wrapper**: Rejected due to excessive memory footprint, heavy runtime DLL dependencies, complex COM/C++ bindings, and Linux display server requirements. Chromium/Edge `--app` mode provides a borderless desktop window using browsers already present on user systems.
- **Immediate Server Shutdown on Client Disconnect**: Rejected because page refreshes (F5) or brief network pauses momentarily drop SSE connections. A 10-second debounce window prevents premature termination.
- **Client-Side HTTP Unload Beacon / Polling**: Rejected because Chromium 88+ throttles background timers to once per 60 seconds on hidden/minimized windows, and unload beacons (`navigator.sendBeacon`) are unreliable during abrupt process kills. Backend SSE socket tracking provides deterministic client presence detection.
- **Third-Party Focus Trap Libraries (`focus-trap-react`, `react-focus-lock`)**: Rejected because they add ~15–30 KB to bundle size, introduce transitive dependencies, and trigger React 19 peer-dependency warnings. Standard DOM querySelector and keydown listeners solve the problem with zero dependencies in < 80 lines of TypeScript.
- **Nested Multi-Group View Transitions**: Rejected because browser View Transitions API isolates named groups from the root snapshot, breaking unified full-viewport clip-path transitions.
- **Continuous DPI Slider (50–600 DPI)**: Rejected because unconstrained raster resolutions cause erratic memory consumption, cache invalidation, and unpredictable vision LLM inference times.

## Consequences
- Standalone desktop app window experience with zero bundled browser bloat.
- Packaged desktop executable runs without console flashes on Windows (`console=False`), with native Win32 dialogs surfacing startup configuration errors.
- Automatic server lifecycle termination when the application window is closed, with safe evacuation of in-progress OCR processing jobs.
- Safe fallback to default browser launching on systems without Chromium-family browsers, including headless WSL2 bridging.
- Test suites run 100% headless across Windows and Linux CI without display server emulators (Xvfb).
- Rich, responsive UI with side-by-side document preview, full-text rendering, theme switching, and real-time SSE progress updates.
- All modal dialogs comply with WCAG 2.1 AA requirements for keyboard navigation, focus containment, and focus restoration.
- Mobile and tablet viewports scroll cleanly through all workspace panels without content truncation.
- Full-screen circular ripple theme transitions render smoothly without clipping or frame tearing.
- Provides desktop integration across Windows, Linux, and WSL2.
- Requires network security middleware (`web/security.py`) to prevent cross-site request attacks.
- Requires building frontend production bundles (`npm run build`) before packaging releases.
