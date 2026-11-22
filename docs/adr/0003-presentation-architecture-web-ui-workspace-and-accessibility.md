# ADR-0003: Presentation Architecture: Web UI Workspace and Accessibility

## Status
Accepted

## Date
2026-11-22

## Context
AksaraSight previously utilized a native desktop GUI built on Tkinter, CustomTkinter, and TkinterDnD2 (`gui/`). This implementation encountered several limitations:
1. **Tcl Threading & Garbage Collection Deadlocks**: The native Tcl/Tk interpreter suffered from intermittent font garbage collection deadlocks (`Font.__del__` race conditions) during rapid window redraws.
2. **Headless Linux CI Incompatibility**: CustomTkinter cannot initialize without a running display server (X11 or Wayland), forcing GUI test suites to be disabled or skipped on Linux CI.
3. **High-DPI Layout Clipping**: Standard 1080p laptop displays at 125% DPI scaling caused severe layout clipping and control overlap during half-screen snapping under Windows.
4. **Brittle Polling Architecture**: The UI relied on periodic polling timers rather than reactive streaming events.
5. **Model Lifecycle UI Latency**: Background model downloads lacked terminal Server-Sent Events (SSE), leaving the UI in a stale "No Local Model" state until manual refresh.
6. **CSS View Transitions API Collisions**: Applying the native View Transitions API (`document.startViewTransition`) to nested layout containers decoupled them from the root snapshot, clipping full-viewport theme transitions.
7. **Accessibility (WCAG 2.1 AA) Deficits**: Modal dialogs lacked focus containment, initial focus targeting, and focus restoration upon exit (WCAG 2.1.2 & 2.4.3). Exported file lists were non-interactive to keyboard users (WCAG 2.1.1). On narrow viewports (< 1024px), single-column layouts clipped content below the fold.
8. **Browser Window Isolation & Process Lifecycle**: Launching a local Web UI inside the user's default browser tab subjects the application to third-party extensions, mixed tab clutter, and lack of standalone desktop window ergonomics. Closing the browser tab leaves the local Uvicorn and inference processes running silently in the background.
9. **Console Windowing & Startup Error Visibility**: Windows desktop executables built with console mode display an unwanted command prompt window behind the UI. Conversely, building in windowed mode (`console=False`) sets standard streams (`sys.stdin`, `sys.stdout`, `sys.stderr`) to `None`, risking runtime crashes in subprocesses or formatters, and causes early startup errors (e.g., port collisions) to fail silently without user feedback.
10. **Desktop Utility Ergonomics & Cognitive Load**: Consumer web aesthetics (such as saturated accents, multi-color gradients, oversized rounded corners, and heavy drop shadows) produce visual fatigue and distraction during intensive document analysis. Desktop document utilities require a low-distraction neutral dark presentation with clear visual hierarchy, disciplined elevation planes, and native Windows 11 / WinUI 3 visual ergonomics.
11. **Synchronous Browser Modals & WAI-ARIA APG Conformance**: Browser-native synchronous modal dialogs (`window.confirm`) block execution threads, produce jarring browser chrome popups, break keyboard navigation continuity, and fail accessibility standards. Professional utility software requires accessible in-DOM dialogs (`alertdialog`) with focus trapping, safe initial focus, and WAI-ARIA APG compliant roving tabindex popovers.

## Decision
1. **Retirement of Native GUI & Adoption of WinUI 3 Desktop Utility Web Workspace**:
   - Retire the native desktop GUI from `main` (permanently frozen at `v1.2.1` on branch `release/1.2`) and replace it with a browser-based local Web UI workspace (`web/` and `frontend/`) designed according to Windows 11 WinUI 3 dark-mode desktop utility principles.
   - The backend is served via FastAPI and Uvicorn on loopback (`127.0.0.1:8000`), pushing real-time progress to a React 19 Single Page Application via Server-Sent Events (SSE).
   - The packaged portable desktop executable (`AksaraSight.exe` / `AksaraSight`) starts the local server and automatically launches the user interface.
   - **Disciplined Dark-Mode Elevation Hierarchy**: Enforce a strict dark-mode surface elevation system with subtle 1px top-lit hairline borders instead of disruptive drop shadows:
     - *Layer 0 (Outer App Shell & Settings Base)*: Pinned to `#202020` base background hosting the 48px navigation rail, top header bar, 26px bottom status bar, and full-canvas Settings view.
     - *Layer 1 (Floating Workspace Panes & Single-Layer Settings Cards)*: Workspace panels and settings section cards float at `#272727` with 8px (`rounded-lg`) corner radii and subtle hairline borders (`border-white/[0.04]` to `border-white/[0.06]`).
     - *Layer 2 (Inset Elements & Modals)*: Inset wells (preview canvas at `#1C1C1C`) and focused modal dialogs (`#2D2D2D` to `#272727` with `border-white/[0.08]`).
   - **Flattened Settings Elevation & Reading Measure**:
     - The Settings view flows directly across the `#202020` base canvas rather than resting on a raised container pane, constrained to a centered `max-w-[960px] mx-auto` measure for optimal typographic line length and ergonomic desktop scanning.
     - Sticky header and footer action bars use `bg-[#202020]/90 backdrop-blur-md` with hairline dividers (`border-white/[0.06]`) to anchor section titles, category tabs, and persistence buttons while scrolling, aligned with the centered `max-w-[960px] mx-auto` content boundaries.
     - Settings options and expanders render as single-layer `#272727` cards (`rounded-lg`, `border-white/[0.06]`) with subtle hairline internal dividers (`border-t border-white/[0.04]` or `border-b border-white/[0.04]`) separating discrete sub-rows and expander content, eliminating unnecessary nested card borders and visual elevation noise.
     - Discrete option grids (such as Local Inference Backend selection and DPI render presets) are promoted directly onto the `#202020` base canvas as flat `#272727` cards with zero outer card nesting, preserving visual hierarchy and preventing elevation ambiguity.
   - **Three-Pane Floating Workspace Layout & Queue Collapse Mechanics**:
     - Organize document extraction operations into a floating 3-pane layout separated by 8px (`gap-2`) gutters over the `#202020` outer shell:
       - *Left Pane*: Collapsible document queue (`FileQueuePanel`, `w-[252px] shrink-0`).
       - *Center Pane*: Document preview canvas (`DocumentPreviewPanel`) featuring an inset `#1C1C1C` preview well (`rounded-md` 6px, `border-white/[0.03]`) that maximizes contrast against rendered document pages.
       - *Right Pane*: Structured extraction inspector (`ExtractedTextPanel`) providing tabbed transcription views (Markdown, Table, Formula, and Raw JSON).
     - **FileQueuePanel Collapse Mechanics**: Implement a mounted collapsible container using `inert={!isQueueOpen}` and `aria-hidden={!isQueueOpen}` rather than unmounting from the React virtual DOM:
       - Preserves scroll positions, loaded thumbnail state, and selected document identifiers during collapse cycles.
       - Transitions width, opacity, and margins smoothly over 200ms using Fluent 2 easing (`ease-fluent` / `cubic-bezier(0, 0, 0, 1)`): expanding to `w-full lg:w-[252px] opacity-100 lg:mr-2 mb-2 lg:mb-0` and collapsing to `w-0 lg:w-0 opacity-0 pointer-events-none border-0 mr-0 mb-0`.
       - Employs a fixed-dimension inner container (`w-full lg:w-[252px] h-full shrink-0`) that isolates inner layout dimensions, completely preventing text re-wrapping or layout jitter during panel transitions.
       - The `inert` attribute completely detaches collapsed panel controls from sequential tab order and accessibility trees.
   - Standardize layered WinUI 3 corner radii: 8px (`rounded-lg`) for workspace panes and settings cards, 6px (`rounded-md`) for controls, inputs, and queue rows, and 4px (`rounded`) for micro badges, strictly eliminating oversized web radii (`rounded-xl`, `rounded-2xl`) and deep drop shadows.
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
   - Reserve the native View Transitions API exclusively for document-wide, full-viewport transformations.
   - Prohibit assigning explicit `view-transition-name` to inner layout containers. Sub-view transitions (Workspace ↔ Settings) use standard CSS transitions (`animate-fade-in`) to maintain a monolithic DOM root for full-screen view transitions.
6. **Zero-Dependency Native Accessibility & Fluent 2 Motion (WCAG 2.2 AA & WAI-ARIA 1.2 APG)**:
   - Implement a lightweight, zero-dependency `useFocusTrap` hook (`frontend/src/hooks/useFocusTrap.ts`) utilizing React refs and standard DOM event listeners. Caches `document.activeElement` prior to opening to restore focus on unmount; traps `Tab` / `Shift+Tab` within modal containers and alertdialogs.
   - **Canonical WinUI 3 Landmark Navigation Rail (`NavRail`)**:
     - Structure the 48px left rail as a semantic `<nav aria-label="Application Navigation">` landmark.
     - View destination triggers (Workspace in upper stack, Settings in footer stack) render as native `<button>` elements with `aria-current="page"` when active, maintaining a natural sequential DOM tab sequence.
     - The upper NavRail stack pairs the Workspace destination button and Queue disclosure button directly as a unified tool group without an intermediate divider, reinforcing their operational affinity for document extraction workflows.
     - A 3px `#60CDFF` active indicator pill transitions vertically between views with an entrance animation (`scale-y` from 0.4 to 1.0 over 167ms).
     - A dedicated disclosure button (`aria-expanded={isQueueOpen}`, `aria-controls="workspace-file-queue"`) toggles the file queue panel independently from view switching.
     - Global desktop keyboard shortcuts provide instant access: `Ctrl+1` (Workspace), `Ctrl+,` (Settings), `Ctrl+B` (Toggle File Queue), and `Ctrl+Shift+L` (Server Logs dialog).
     - In-page Settings category tabs retain `role="tablist"` and `role="tab"` semantics with roving tabindex navigation (`tabIndex={active ? 0 : -1}`), Arrow key navigation (`ArrowLeft`/`ArrowRight`), `Home`, and `End` keys.
   - **WAI-ARIA 1.2 APG Dialog & RadioGroup Popover (`ExtractionOptionsPopover`)**: Implement a non-modal dialog (`role="dialog"`, `aria-label="Extraction Options"`) containing two discrete option groups (`role="radiogroup"` for Extraction Target Modes and Scan Detail Resolutions). Radio options (`role="radio"`, `aria-checked`) feature roving tabindex (`tabIndex={checked ? 0 : -1}`), Arrow key navigation (`ArrowDown`/`ArrowUp`), `Home`/`End` bounds jumping, and `Tab`/`Shift+Tab` traversal across groups. `Escape` dismisses the popover and restores focus to the trigger button.
   - **WAI-ARIA 1.2 APG Menu Button (`ExportDropdown`)**: Implement an accessible dropdown menu (`role="menu"`, `aria-haspopup="menu"`, `aria-expanded={isOpen}`) with items assigned `role="menuitem"`. Supports `ArrowDown`/`ArrowUp` navigation with wraparound, `Home`/`End` keys, `Enter`/`Space` activation, and `Escape` collapse with focus restoration to the trigger button.
   - **WCAG 2.2 SC 1.3.1 Table Header Scoping (`TableRenderer`)**: Enforce explicit semantic header association across parsed tables: `<th scope="col">` for column headers and `<th scope="row">` for lead row headers, ensuring assistive technologies correctly contextualize data cells during tabular navigation.
   - **WCAG 2.2 SC 2.5.8 Target Size Compliance**: Enforce minimum 24px x 24px bounding boxes on interactive touch targets across toggles and buttons, sizing configuration switches to `h-6 w-11` (24px height).
   - **Contrast & Keyboard Navigation**: Pinned WinUI 3 dark tokens satisfy WCAG 2.2 AA contrast (>= 4.5:1 for body copy; `#60CDFF` accent against `#000000` text provides 11.65:1 contrast).
   - **Calibrated Fluent 2 Motion & Reduced Motion Safeguards**:
     - Standardize transition timing and curves across interactive surfaces using Fluent 2 bezier timing (`--ease-fluent`: `cubic-bezier(0, 0, 0, 1)`): 167ms fast transitions for active indicator pills and category tabs, and 200ms normal transitions for panel collapses (`fadeIn` with 6px vertical entrance slide-up, `slideUp` with 8px vertical entrance slide-up).
     - Under `prefers-reduced-motion: reduce`, enforce universal immediate transitions (`animation-duration: 0.01ms !important`, `transition-duration: 0.01ms !important`, `scroll-behavior: auto !important`) across all elements while explicitly preserving operational activity spinners (`.animate-spin`, `[data-animate-spin]`), slowing rotation to a calm 2.5s linear duration to retain ongoing status feedback without vestibular triggers.
7. **Responsive Viewport Overflow Resilience**:
   - Configure `<main>` in `frontend/src/App.tsx` with `overflow-y-auto lg:overflow-hidden` and provide minimum panel heights (`min-h-[340px]`, `min-h-[460px] lg:h-full`), enabling smooth vertical scrolling on mobile/tablet viewports while preserving fixed 3-column height on desktop displays.
8. **Discrete Parameter Controls & Real-Time SSE Synchronization**:
   - Replace continuous range sliders with structured 2x2 interactive Card Buttons (72, 100, 150, 200 DPI) incorporating semantic `aria-pressed`, tactile depress feedback, and descriptive copy, promoted directly onto the `#202020` base canvas as flat `#272727` cards with zero outer card nesting.
   - Emit an explicit terminal SSE payload (`model_download_progress` with `status: "completed"`) from the backend downloader thread, triggering immediate UI state refetch without manual page reload.
   - Synchronize workspace extraction DPI and global settings bidirectionally (`PATCH /api/settings`).
9. **Cross-Platform Desktop Integration**:
   - **File Chooser**: Win32 FileDialog on Windows; `zenity` (or fallback `kdialog`) on Linux desktop.
   - **Directory Reveal**: Windows Explorer on Windows; `xdg-open` on Linux with returncode validation.
   - **WSL Browser Bridging**: In headless WSL environments, route browser launches via `wslview -- <url>` or `powershell.exe Start-Process '<safe_url>'` with single-quote escaping and URL scheme validation.
10. **Modular Component Architecture & Accessible Dialog Architecture**:
    - Decompose monolithic frontend views into focused presentational views and specialized sub-components, maintaining a modular design target (< 350 LOC per file) to prevent architectural drift:
      - Workspace views (`ExtractedTextPanel`, `DocumentPreviewPanel`, `FileQueuePanel`) decompose into specialized sub-components (`QueueItemRow`, `ExtractionOptionsPopover`, `ExportDropdown`) and dedicated format renderers (`FormulaRenderer`, `TableRenderer`, `MarkdownRenderer`).
      - Configuration views (`SettingsView`) isolate settings categories into dedicated tabs (`SettingsEngineTab`, `SettingsProcessingTab`, `SettingsAdvancedTab`) and runtime diagnostic cards (`ManagedRuntimeSection`, `ModelWeightsSection`, `DoctorDiagnosticSection`).
    - Encapsulate domain lifecycles into dedicated custom hooks:
      - `useExtractionQueue`: Manages document queue state, batch dispatch, active extraction polling, SSE event reconciliation, and abort handling.
      - `useServerStatus`: Monitors local server health, backend start/stop lifecycle, and live VRAM telemetry.
      - `useVramTelemetry`: Decoupled NVML telemetry with Page Visibility API polling suspension (`document.hidden`) and shallow equality bailout.
      - `useSettings`: Manages engine configuration state, persistence to local backend settings, and dirty-state tracking.
      - `useToast`: Dispatches non-blocking, accessible status notifications.
    - Eradicate untyped browser globals and ad-hoc singletons:
      - Replace `window.__eventSource` with typed `ServerEventsContext` (`frontend/src/context/ServerEventsContext.tsx`), providing type-safe Server-Sent Events subscriptions with automatic listener cleanup on unmount.
      - Replace blocking native `window.alert()` calls with an accessible, non-blocking `ToastContext` (`frontend/src/context/ToastContext.tsx`) rendering polite screen-reader alerts via `ToastContainer`.
      - **Elimination of Synchronous `window.confirm`**: Replace blocking native browser confirm dialogs with in-DOM WinUI 3 accessible alert dialogs (`role="alertdialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby`). Place initial focus on the "Cancel" safe action to prevent accidental destructive actions, contain keyboard focus with `useFocusTrap`, support Escape and backdrop click dismissal, and restore focus to the triggering element upon exit.
11. **Offline KaTeX Math Formula Rendering & Font Asset Bundling**:
    - Incorporate KaTeX (0.19.1) for offline client-side LaTeX math formula rendering (`FormulaRenderer.tsx`) across preview and transcription panels.
    - Enforce defensive execution constraints: `trust: false` (prohibits dangerous KaTeX commands and arbitrary HTML injection), `throwOnError: false` (renders fallback raw text gracefully without crashing), and `strict: false`.
    - Route all KaTeX font assets (`.woff2`, `.ttf`, etc.) into `assets/fonts/` via Vite 8 `rolldownOptions.output.assetFileNames` to guarantee full functionality in strictly air-gapped environments without CDN requests.
12. **Live In-Process NVML VRAM Telemetry & Status Bar Isolation**:
    - Expose a dedicated hardware telemetry endpoint (`GET /api/hardware/vram`) in `web/app.py`, offloading NVML queries to worker threads (`asyncio.to_thread`).
    - Isolate live telemetry display into a dedicated 26px `BottomStatusBar.tsx` anchored at Layer 0 alongside the engine process PID badge.
    - Poll telemetry at a 6-second interval via `useVramTelemetry` with Page Visibility API polling suspension when the application window or tab is hidden (`document.hidden`).
    - Surface device name, total memory, used memory, and a dynamic color-coded usage bar (green <= 65%, amber > 65%, red > 85%) for NVIDIA GPUs while remaining inert on non-NVIDIA systems.

## Alternatives Considered & Rejected
- **PySide6 / PyQt6**: Rejected due to heavy distribution size (>150 MB binary overhead), complex LGPL licensing, and continued display server requirements in headless CI.
- **CustomTkinter Refactoring via Controller/Mediator**: Rejected because code refactoring could not resolve underlying platform limitations (Tcl threading deadlocks, Linux CI display requirements, DPI scaling glitches).
- **Electron / WebView2 / PyWebView Application Wrapper**: Rejected due to excessive memory footprint, heavy runtime DLL dependencies, complex COM/C++ bindings, and Linux display server requirements. Chromium/Edge `--app` mode provides a borderless desktop window using browsers already present on user systems.
- **Immediate Server Shutdown on Client Disconnect**: Rejected because page refreshes (F5) or brief network pauses momentarily drop SSE connections. A 10-second debounce window prevents premature termination.
- **Client-Side HTTP Unload Beacon / Polling**: Rejected because Chromium 88+ throttles background timers to once per 60 seconds on hidden/minimized windows, and unload beacons (`navigator.sendBeacon`) are unreliable during abrupt process kills. Backend SSE socket tracking provides deterministic client presence detection.
- **Third-Party Focus Trap Libraries (`focus-trap-react`, `react-focus-lock`)**: Rejected because they add ~15–30 KB to bundle size, introduce transitive dependencies, and trigger React 19 peer-dependency warnings. Standard DOM querySelector and keydown listeners solve the problem with zero dependencies in a compact custom hook.
- **Nested Multi-Group View Transitions**: Rejected because browser View Transitions API isolates named groups from the root snapshot, breaking unified full-viewport clip-path transitions.
- **Continuous DPI Slider (50–600 DPI)**: Rejected because unconstrained raster resolutions cause erratic memory consumption, cache invalidation, and unpredictable vision LLM inference times.
- **External CDN for KaTeX / MathJax**: Rejected because external asset loading violates the 100% offline security and privacy architecture.
- **Unrestricted KaTeX Trust Flag (`trust: true`)**: Rejected because processing unvetted OCR transcriptions with `trust: true` introduces script execution and XSS risks.
- **Global `window.alert` and Unmanaged `window.__eventSource` Singletons**: Rejected because native blocking dialogs disrupt screen readers and keyboard workflows, while unmanaged global event sources cause connection leaks across component remounts.
- **Synchronous Browser Modals (`window.confirm`)**: Rejected because native browser dialogs halt JavaScript execution, display un-stylable browser chrome, cannot be trapped within standard accessibility trees, and violate keyboard accessibility patterns.
- **Consumer Web Visual Styling (Vibrant Accents, Multi-Color Gradients, Deep Drop Shadows)**: Rejected because high-saturation styling and heavy decorative shadows create visual noise and eye fatigue during dense document transcription; a neutral dark surface with 1px top-lit hairlines provides high contrast and clarity.
- **Unmounting FileQueuePanel on Collapse**: Rejected because unmounting removes the component from the React tree, discarding internal scroll offsets, queue selection states, and thumbnail caches; mounting with `inert={!isQueueOpen}`, `aria-hidden`, and CSS width/opacity transitions preserves state while fully disconnecting collapsed elements from the accessibility tree and keyboard sequence.
- **Nested Multi-Layer Card Stacking in Settings**: Rejected because nesting `#2D2D2D` cards within floating `#272727` surface panels created excessive visual border noise and elevation ambiguity; flattening Settings directly onto `#202020` with single-layer `#272727` cards, promoting backend and DPI option grids directly onto the base canvas with zero outer card nesting, and using hairline internal dividers aligns with canonical Windows 11 Fluent 2 layout guidelines.
- **Intermediate Rail Divider Between Workspace and Queue Controls**: Rejected because separating the Workspace view trigger and Queue panel disclosure with an intermediate divider disrupted visual cohesion; pairing them directly into a unified upper tool group clarifies their functional relationship in document processing.
- **Single Composite Tablist for Application Navigation Rail**: Rejected because the navigation rail contains distinct interactive roles: view destinations, a panel collapse disclosure toggle, and a modal launcher button. Treating the entire rail as a `tablist` broke landmark accessibility; structuring as `<nav aria-label="Application Navigation">` with destination buttons (`aria-current="page"`), disclosure attributes, and sequential tab order conforms to WAI-ARIA landmark navigation patterns while preserving `role="tablist"` for in-page category switches.
- **Full Spinner Freeze Under Reduced Motion**: Rejected because completely freezing progress indicators leaves users unable to distinguish active processing from hung background threads; a calmed 2.5s rotation provides clear status feedback without triggering vestibular triggers.

## Consequences
- Standalone desktop app window experience with zero bundled browser bloat.
- Packaged desktop executable runs without console flashes on Windows (`console=False`), with native Win32 dialogs surfacing startup configuration errors.
- Automatic server lifecycle termination when the application window is closed, with safe evacuation of in-progress OCR processing jobs.
- Safe fallback to default browser launching on systems without Chromium-family browsers, including headless WSL2 bridging.
- Test suites run 100% headless across Windows and Linux CI without display server emulators (Xvfb).
- Cohesive Windows 11 WinUI 3 dark-mode utility aesthetic with a disciplined elevation hierarchy (#202020 base canvas, #272727 floating workspace panes and single-layer settings cards, and inset #1C1C1C preview well) with 8px gutters and max-w-[960px] mx-auto settings measure.
- Flattened Settings elevation flowing directly on the `#202020` base canvas with translucent sticky header and footer action bars (`bg-[#202020]/90 backdrop-blur-md`), flat #272727 backend and DPI option grids with zero outer card nesting, and hairline internal dividers.
- Smooth 200ms `FileQueuePanel` collapse mechanics preserving queue and scroll state via `inert={!isQueueOpen}` and `aria-hidden={!isQueueOpen}` with an isolated inner container dimension.
- Full WCAG 2.2 AA accessibility compliance: canonical `<nav aria-label="Application Navigation">` landmark with view destination buttons (`aria-current="page"`), upper NavRail stack pairing Workspace destination and Queue disclosure directly as a unified tool group without an intermediate divider, sequential DOM tab sequence, global keyboard shortcuts (`Ctrl+1`, `Ctrl+,`, `Ctrl+B`, `Ctrl+Shift+L`), animated `scale-y` active indicator pill, 24px target sizes (`h-6 w-11` switches), WAI-ARIA 1.2 APG Dialog & RadioGroup popover, APG Menu Button, and WCAG 1.3.1 table header scoping (`scope="col"` and `scope="row"`).
- Calibrated Fluent 2 motion system (`cubic-bezier(0, 0, 0, 1)`, 167ms fast / 200ms normal, 6px–8px vertical entrance slide-up) with universal 0.01ms reduced-motion collapse preserving `.animate-spin` at 2.5s.
- In-DOM `role="alertdialog"` with initial focus on safe Cancel action, eliminating thread-blocking `window.confirm`.
- Rich, responsive UI with side-by-side document preview, full-text rendering, and real-time SSE progress updates.
- Modular frontend architecture with presentational views decomposed into specialized sub-components (< 350 LOC design target) and clear custom domain hook separation.
- Full client-side LaTeX formula rendering with KaTeX operating 100% offline via Vite 8 Rolldown font routing without external CDN requests.
- Type-safe, leak-free Server-Sent Events management via `ServerEventsContext` and non-blocking notifications via `ToastContext`.
- Live in-process NVML VRAM telemetry monitoring isolated in a 26px bottom status bar with Page Visibility API polling suspension.
- Mobile and tablet viewports scroll cleanly through all workspace panels without content truncation.
- Provides desktop integration across Windows, Linux, and WSL2.
- Requires network security middleware (`web/security.py`) to prevent cross-site request attacks.
- Requires building frontend production bundles (`npm run build`) before packaging releases.
