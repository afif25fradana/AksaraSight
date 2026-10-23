# ADR-0008: Real-Time Model Lifecycle Streaming and CSS View Transitions Isolation Boundary

## Status
Accepted

## Date
2026-10-21

## Context
1. **Model Weight Lifecycle Latency**: Local model downloads run in a dedicated background worker thread (`_bg_download` in `web/app.py`). Previously, upon download completion, the backend did not emit a distinct completion event across Server-Sent Events (SSE). The frontend UI remained in a stale "No Local Model" state until the user performed a manual browser refresh or waited for coarse polling cycles.
2. **Configuration Desynchronization**: Workspace extraction resolution (`selectedDpi` in `ExtractedTextPanel`) and global settings (`Settings.dpi` in `SettingsView`) operated as disjoint states. Changing the DPI in the workspace did not update global configuration or persist to `.env`, leading to user confusion and inconsistent scan runs.
3. **CSS View Transitions API Collision**: Introducing modern layout transitions using the native View Transitions API (`document.startViewTransition`) revealed an isolation collision. When child layout containers (such as the main workspace `<main>` or settings view `<div>`) were assigned explicit `view-transition-name: tab-view`, the browser decoupled them from `::view-transition-group(root)`. Consequently, full-viewport transitions—specifically the signature circular ripple (`ripple-reveal` mask on `::view-transition-new(root)`) during theme toggles—had their viewports clipped and broken by the isolated sub-containers.
4. **Continuous vs. Discrete Control Mismatch**: The DPI setting was rendered using a continuous range input (`<input type="range">`), a stepped text label row, and static info cards. Because OCR rasterization accepts only discrete, validated presets (72, 100, 150, 200 DPI), the range slider presented visual and ergonomic redundancy.

## Decision
1. **Explicit SSE Model Completion Broadcasting**:
   - The backend `_bg_download` thread emits an explicit terminal payload over the SSE event `model_download_progress` (`status: "completed"`, `downloaded: True`, `is_downloading: False`, `percent: 100.0`).
   - The frontend (`App.tsx` and `SettingsView.tsx`) listens for this terminal event, immediately refetches model status, and transitions the badge to "Verified Local Weights" without requiring page reloads.
2. **Bidirectional Settings & Workspace DPI Synchronization**:
   - The frontend workspace hydrates `selectedDpi` from `GET /api/settings` on initial load.
   - Adjusting workspace DPI automatically sends `PATCH /api/settings` to update and persist the backend configuration.
   - Saving settings in `SettingsView` synchronizes back to the workspace DPI state.
3. **CSS View Transitions API Isolation Boundary**:
   - Reserve the native View Transitions API exclusively for document-wide, full-viewport transformations (the circular ripple theme transition).
   - Prohibit assigning explicit `view-transition-name` to inner layout containers. Sub-view transitions (such as Workspace ↔ Settings navigation) must use standard CSS transitions / keyframe animations (`animate-fade-in`) to keep the DOM root monolithic for full-screen view transitions.
4. **Discrete Parameter Card Buttons**:
   - Replace continuous `<input type="range">` controls with structured 2x2 interactive Card Buttons for discrete configuration options (72, 100, 150, 200 DPI), incorporating semantic `aria-pressed`, tactile depress feedback (`active:scale-[0.98]`), and embedded descriptive copy.

## Alternatives Considered & Rejected
- **Client-Side Polling for Model Download Completion**: Rejected because SSE connections are already open and active; client-side polling introduces unnecessary network overhead, loopback socket churn, and latency.
- **Nested Multi-Group View Transitions**: Rejected because browser View Transitions API specification isolates named groups from the root snapshot, making unified full-viewport clip-path transitions impossible without complex synchronized multi-element shaders.
- **Continuous DPI Slider (50–600 DPI)**: Rejected because unconstrained raster resolutions cause erratic memory consumption, cache invalidation, and unpredictable vision LLM inference times. Pinned presets ensure predictable quality and throughput.

## Consequences
- Model download completion reflects instantaneously across all views in real time.
- Settings and workspace scan options remain tightly synchronized with zero drift.
- Full-screen circular ripple theme transitions render smoothly without clipping or frame tearing.
- UI ergonomics match backend constraints, eliminating redundant controls and confusing continuous sliders.
