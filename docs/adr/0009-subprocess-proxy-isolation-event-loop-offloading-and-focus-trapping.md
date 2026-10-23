# ADR-0009: Subprocess Proxy Isolation, Complete Event Loop Thread Offloading, and Zero-Dependency Modal Focus Trapping

## Status
Accepted

## Date
2026-10-21

## Context
1. **Event Loop Starvation during Server Lifecycle Operations**: In `web/app.py`, `post_server_start()` and `post_server_stop()` are declared as `async def` route handlers on FastAPI's main asyncio event loop. However, `ServerManager.start()` performs synchronous TCP socket probing and HTTP health checks (up to 3.0s), while `ServerManager.stop()` calls `proc.terminate()` and `proc.wait(timeout=3.0)`. Executing these blocking calls directly on the asyncio loop violated ADR-0006 Decision 1, starving concurrent HTTP requests and interrupting real-time Server-Sent Events (`/api/events`).
2. **Subprocess Proxy Inheritance**: When `ServerManager` spawned `llama-server` via `subprocess.Popen`, it inherited the host process environment (`os.environ`). On machines configured with system-wide proxy environment variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`), the child process could route loopback traffic through external proxies, creating an anti-exfiltration risk and conflicting with ADR-0005.
3. **Accessibility (WCAG 2.1.2 & 2.4.3) in Modal Dialogs**: The application modals (`OutputFolderModal`, `ServerLogsModal`, and the security dialog in `SettingsView`) declared `role="dialog"` or `role="alertdialog"` and `aria-modal="true"`. However, they lacked focus containment (Tab key escaped the dialog into background panels), initial focus management, and return focus restoration on close. Additionally, exported file items in `OutputFolderModal` were rendered as `<div>` elements inaccessible to keyboard users (WCAG 2.1.1).
4. **Responsive Single-Column Viewport Clipping**: On viewports narrower than `lg` (1024px), the 3-pane layout collapsed into a single column (`grid-cols-1`). Because `<main>` enforced `overflow-hidden`, preview and text panels below the fold were clipped and permanently inaccessible.

## Decision
1. **Complete Event Loop Offloading for Server Lifecycle (P1-01)**:
   - Offload `app_server_manager.start()` and `app_server_manager.stop()` in `web/app.py` to worker threads using `await asyncio.to_thread(...)`.
   - Keep state mutation (`app.state.server_managed = ...`) and validation on the main coroutine thread, preserving thread-safety while preventing event loop starvation.
2. **Subprocess Environment Sanitization & Anti-Exfiltration (SEC-P2-02)**:
   - When spawning managed child processes in `core/server_manager.py`, clone `os.environ` into an isolated `sub_env`.
   - Strip all proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and lowercase variants) and explicitly enforce `sub_env["NO_PROXY"] = "*"` and `sub_env["no_proxy"] = "*"`.
   - Pass `env=sub_env` to `subprocess.Popen`.
3. **Zero-Dependency Native Focus Trap Hook (`useFocusTrap`)**:
   - Implement `useFocusTrap` (`frontend/src/hooks/useFocusTrap.ts`) utilizing React refs and standard DOM event listeners.
   - Cache `document.activeElement` prior to opening to restore focus upon unmount.
   - Query focusable elements dynamically and trap `Tab` / `Shift+Tab` within the container.
   - Avoid introducing heavy third-party npm dependencies (`focus-trap`, `react-focus-lock`) in adherence to the project's minimalist (YAGNI/anti-slop) architectural guidelines.
4. **Semantic Interactive Controls for File Lists**:
   - Provide `role="button"`, `tabIndex={0}`, `aria-pressed`, and `onKeyDown` (`Enter` and `Space`) on exported file items in `OutputFolderModal.tsx`.
5. **Responsive Viewport Overflow Resilience**:
   - Update `<main>` in `frontend/src/App.tsx` to `overflow-y-auto lg:overflow-hidden` and supply responsive minimum heights (`min-h-[340px]` and `min-h-[460px] lg:h-full`) to panel columns, ensuring vertical scrolling on mobile/tablet viewports while preserving fixed 3-column height on desktop.

## Alternatives Considered & Rejected
- **Third-Party Focus Trap Libraries (`focus-trap-react`, `react-focus-lock`)**: Rejected because they add ~15–30 KB to the bundle, bring transitive dependencies, and introduce React 19 peer-dependency warnings. Standard DOM querySelector and keydown listeners solve the problem with zero dependencies in < 80 lines of TypeScript.
- **FastAPI Synchronous `def` Handlers**: Rejected because converting `post_server_start` and `post_server_stop` to synchronous `def` runs the entire route in Starlette's threadpool, breaking consistency with the async architecture in `web/app.py` and violating ADR-0006.
- **Global Proxy Disabling via OS Registry**: Rejected because application processes should not tamper with host system network settings; subprocess environment isolation guarantees local immunity without side effects.

## Consequences
- Inference engine startup and shutdown no longer cause UI freezes, jitter, or SSE stream drops.
- Child processes are completely isolated from host proxy configurations, reinforcing 100% offline security.
- All modal dialogs comply with WCAG 2.1 Level AA requirements for keyboard navigation, focus containment, and focus restoration.
- Mobile and tablet viewports can scroll through all workspace panels without content truncation.
