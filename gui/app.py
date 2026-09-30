"""GUI Application for AksaraSight desktop studio."""

from dataclasses import dataclass
from enum import Enum
import io
import json
import logging
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
from tkinter import filedialog
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import customtkinter as ctk
from PIL import Image
import tkinterdnd2 as tkdnd
import tkinterdnd2.TkinterDnD as tdnd

from config.settings import Settings
from core.constants import SUPPORTED_EXTENSIONS, __version__
from core.engine import OCREngine
from core.formatter import (
    resolve_unique_stem,
    save_artifacts,
)
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat, PageResult
from core.pipeline import PipelineError, rasterize_page
from core.server_manager import ServerManager, ServerOwnership, ServerStatus, ServerStatusInfo
# Color tokens (WCAG 2.1 AA verified)
# Re-exported from gui.theme for backward compatibility
from gui.theme import (
    COLOR_ACCENT_DISABLED,
    COLOR_ACCENT_DISABLED_TEXT,
    COLOR_ACCENT_HOVER,
    COLOR_ACCENT_PRIMARY,
    COLOR_ACCENT_TEXT,
    COLOR_CANVAS_BG,
    COLOR_CHIP_IMG_BG,
    COLOR_CHIP_IMG_TEXT,
    COLOR_CHIP_PDF_BG,
    COLOR_CHIP_PDF_TEXT,
    COLOR_DRAGOVER_BG,
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_ROW_SELECTED_BG,
    COLOR_SCROLLBAR_THUMB,
    COLOR_SCROLLBAR_THUMB_HOVER,
    COLOR_STATUS_CANCELLED,
    COLOR_STATUS_ERROR,
    COLOR_STATUS_FAILED,
    COLOR_STATUS_PARTIAL,
    COLOR_STATUS_PROCESSING,
    COLOR_STATUS_QUEUED,
    COLOR_STATUS_SUCCESS,
    COLOR_STATUS_WARNING,
    COLOR_SURFACE_1,
    COLOR_SURFACE_2,
    COLOR_SURFACE_BORDER,
    COLOR_SURFACE_BORDER_HOVER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_SUBTLE,
    align_segmented_button_corners,
    apply_window_icon,
)

from gui.settings_window import SettingsWindow
from gui.preview_highlighter import MarkdownHighlighter
from gui.image_preview import ImagePreviewController
from gui.export_controller import ExportController
from gui.server_controller import ServerUIController
from gui.worker_coordinator import WorkerCoordinator, WorkerEvent, WorkerEventType
from gui.queue_manager import (
    QueueItem,
    QueueItemStatus,
    QueueManager,
)

logger = logging.getLogger(__name__)


def _friendly_err(exc: Any) -> str:
    """Map common exceptions to user-friendly plain-language error messages for footer/UI display.

    Diagnostic details are preserved in log files via logger; this helper filters out
    technical OS error codes (e.g. WinError 2, Errno 13) and raw tracebacks from the UI.
    """
    if exc is None:
        return "Unknown error"
    if not isinstance(exc, Exception):
        return str(exc)[:120]

    if isinstance(exc, FileNotFoundError):
        if getattr(exc, "errno", None) is not None:
            fn = getattr(exc, "filename", None)
            return f"File not found: {fn}" if fn else f"File not found: {exc.strerror or str(exc)}"
        return str(exc)

    if isinstance(exc, PermissionError):
        fn = getattr(exc, "filename", None)
        return f"Permission denied: {fn}" if fn else "Permission denied — check folder permissions."

    if isinstance(exc, ConnectionError):
        return f"Connection failed: {exc}"

    return str(exc)[:120]


def _init_tkinterdnd(tkroot: Any) -> str:
    """Initialize TkinterDnD with forward-slash normalized auto_path for Windows/Tcl 9 compatibility.

    WHY THIS NORMALIZATION IS REQUIRED:
    On Windows (specifically Python 3.14 with Tcl 9), standard Windows backslash paths
    (e.g. 'C:\\Users\\...') contain backslash escape sequences like '\\U'. In Tcl 9, '\\U'
    is parsed as a Unicode escape sequence ('\\UXXXXXXXX'). When TkinterDnD's internal
    pkgIndex.tcl evaluates "tkdnd::source {$dir/tkdnd.tcl}", unescaped backslashes in $dir
    corrupt the interpolated path string, causing Tcl package loading to fail intermittently
    with 'couldn't read file ".../tkdnd.tcl": no such file or directory'.
    Normalizing the directory path with forward slashes (str(target_dir).replace('\\', '/'))
    before appending to Tcl's 'auto_path' ensures Tcl interprets the path cleanly without
    escape sequence corruption.
    """
    try:
        import platform
        machine = os.environ.get("PROCESSOR_ARCHITECTURE", platform.machine())
        platform_rep = "win-arm64" if machine == "ARM64" else ("win-x64" if "64" in machine else "win-x86")
        tcl_major = int(tkroot.tk.call("info", "tclversion").split(".")[0])
        subfolder = f"{platform_rep}-tcl9" if tcl_major >= 9 else platform_rep
        target_dir = (Path(tkdnd.__file__).parent / "tkdnd" / subfolder).resolve()
        if target_dir.is_dir():
            target_str = str(target_dir).replace("\\", "/")
            tkroot.tk.call("lappend", "auto_path", target_str)
            try:
                ver = tkroot.tk.call("package", "require", "tkdnd")
                tdnd.TkdndVersion = ver
                return str(ver)
            except Exception:
                pass
    except Exception:
        pass
    return tdnd._require(tkroot)





class OCRApp(ctk.CTk, tdnd.DnDWrapper):
    """AksaraSight Local desktop studio application window.

    Implements a responsive 2-column layout:
    - Left: Native drag-and-drop ingestion card & scrollable queue manager table.
    - Right: 3-tab split preview pane (Raw Markdown, Preview, JSON Tree) & action bar.
    - Footer: Live execution status and document counters.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        engine: Optional[OCREngine] = None,
        server_manager: Optional[ServerManager] = None,
    ) -> None:
        """Initialize the GUI application window, layout, and worker thread."""
        super().__init__()
        self.TkdndVersion = _init_tkinterdnd(self)
        try:
            self.tk.call("proc", "bgerror", "msg", "")
        except Exception:
            pass

        engine_settings = getattr(engine, "settings", None)
        if not isinstance(engine_settings, Settings):
            engine_settings = None
        self.settings = settings or engine_settings or Settings.from_env()
        self.engine = engine or OCREngine(self.settings)
        self.server_manager = server_manager or ServerManager(settings=self.settings)
        if hasattr(self.server_manager, "on_lifecycle_change") and hasattr(self.engine, "invalidate_backend_verification"):
            self.server_manager.on_lifecycle_change = self.engine.invalidate_backend_verification
        self._settings_window: Optional[SettingsWindow] = None
        self._server_controller: Optional[ServerUIController] = None
        self._legacy_server_poller_thread: Optional[threading.Thread] = None
        self._legacy_server_stop_thread: Optional[threading.Thread] = None
        self._legacy_server_start_thread: Optional[threading.Thread] = None
        self._legacy_last_applied_server_status: Optional[Tuple[ServerStatus, ServerOwnership]] = None
        self._highlighter = MarkdownHighlighter()

        # Window appearance and geometry
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=COLOR_CANVAS_BG)
        self.title("AksaraSight Local Studio")
        apply_window_icon(self)
        self.geometry("1020x680")
        self.minsize(820, 520)

        # Thread synchronization queues and state
        self._task_queue_backing: queue.Queue[Optional[Path]] = queue.Queue()
        self._result_queue_backing: queue.Queue[WorkerEvent] = queue.Queue()
        self._shutdown_event = threading.Event()
        self._is_shutting_down = False
        self._poll_id_legacy: Optional[str] = None

        # State tracking
        self._queue_manager: Optional[QueueManager] = None
        self._worker_coordinator: Optional[WorkerCoordinator] = None
        self._worker_thread_legacy: Optional[threading.Thread] = None
        self._current_cancel_event_legacy: Optional[threading.Event] = None
        self._pending_engine_settings_legacy: Optional[Settings] = None
        self._success_count_legacy: int = 0
        self._failed_count_legacy: int = 0
        self._progress_indeterminate_legacy: bool = False
        self._image_preview: Optional[ImagePreviewController] = None
        self._legacy_current_image_page_idx: int = 0
        self._legacy_current_ctk_image: Optional[ctk.CTkImage] = None
        self._is_exporting_legacy: bool = False
        self._export_controller: Optional[ExportController] = None
        self._runtime_download_thread: Optional[threading.Thread] = None
        self._ui_callback_queue: queue.Queue[Tuple[Any, tuple, dict]] = queue.Queue()

        # Build UI layout
        self._build_layout()

        # Queue manager controller
        self._queue_manager = QueueManager(
            queue_scroll=self._queue_scroll,
            empty_queue_label=self._empty_queue_label,
            queue_title=self._queue_title,
            queue_cleanup_hint=self._queue_cleanup_hint,
            task_queue=self._task_queue,
            safe_after=self._safe_after,
            after=self.after,
            update_footer=self._update_footer,
            get_current_dpi=lambda: getattr(self.settings, "dpi", None),
            is_shutting_down=lambda: self._is_shutting_down,
            drain_ui_callbacks=self._drain_ui_callbacks,
            update_ui=self.update,
            on_selection_changed=self._on_selection_changed,
            on_queue_emptied=self._on_queue_emptied,
            on_queue_changed=self._update_action_buttons,
        )

        if self._export_controller is not None:
            self._export_controller.queue_manager = self._queue_manager

        # Auto-start managed server if enabled and start periodic health poller
        if self._server_controller is not None:
            self._server_controller.auto_start_if_needed()
            self._server_controller.start_poller()
        else:
            self._start_server_poller()

        # Protocol handlers
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Worker coordinator controller
        self._worker_coordinator = WorkerCoordinator(
            engine=lambda: self.engine,
            settings=lambda: self.settings,
            queue_manager=lambda: self._queue_manager,
            task_queue=self._task_queue_backing,
            result_queue=self._result_queue_backing,
            export_controller=self._export_controller,
            image_preview=self._image_preview,
            safe_after=self._safe_after,
            after=lambda *args, **kwargs: self.after(*args, **kwargs),
            after_cancel=lambda *args, **kwargs: self.after_cancel(*args, **kwargs),
            is_shutting_down=lambda: self._is_shutting_down,
            shutdown_event=self._shutdown_event,
            drain_ui_callbacks=self._drain_ui_callbacks,
            update_footer=self._update_footer,
            render_preview=self._render_preview,
            update_action_buttons=self._update_action_buttons,
            format_queue_item_meta=self._format_queue_item_meta,
            progress_bar=self._progress_bar,
            lbl_page_counter=self._lbl_page_counter,
            lbl_progress_info=self._lbl_progress_info,
            btn_cancel=self._btn_cancel,
            poll_callback=self._process_result_queue,
        )
        if self._current_cancel_event_legacy is not None:
            self._worker_coordinator.current_cancel_event = self._current_cancel_event_legacy
        if self._pending_engine_settings_legacy is not None:
            self._worker_coordinator.pending_engine_settings = self._pending_engine_settings_legacy

        # Start background worker thread and result queue processor
        self._worker_coordinator.start()

    # ponytail: remove in Phase 5 after test_gui.py migrated to ImagePreviewController
    @property
    def _current_image_page_idx(self) -> int:
        if self._image_preview is not None:
            return self._image_preview.current_page_idx
        return self._legacy_current_image_page_idx

    # ponytail: remove in Phase 5 after test_gui.py migrated to ImagePreviewController
    @_current_image_page_idx.setter
    def _current_image_page_idx(self, value: int) -> None:
        self._legacy_current_image_page_idx = value
        if self._image_preview is not None:
            self._image_preview.current_page_idx = value

    # ponytail: remove in Phase 5 after test_gui.py migrated to ImagePreviewController
    @property
    def _current_ctk_image(self) -> Optional[ctk.CTkImage]:
        if self._image_preview is not None:
            return self._image_preview.current_ctk_image
        return self._legacy_current_ctk_image

    # ponytail: remove in Phase 5 after test_gui.py migrated to ImagePreviewController
    @_current_ctk_image.setter
    def _current_ctk_image(self, value: Optional[ctk.CTkImage]) -> None:
        self._legacy_current_ctk_image = value
        if self._image_preview is not None:
            self._image_preview.current_ctk_image = value

    def _on_selection_changed(self, item: Optional[QueueItem], selection_changed: bool) -> None:
        """Handle selection change notifications from QueueManager."""
        if item is not None:
            if selection_changed:
                self._current_image_page_idx = 0
            self._render_preview(item)

    # ponytail: remove in Phase 5
    @property
    def _queue_items(self) -> Dict[str, QueueItem]:
        return self._queue_manager.items

    # ponytail: remove in Phase 5
    @property
    def _selected_item_id(self) -> Optional[str]:
        return self._queue_manager.selected_item_id

    # ponytail: remove in Phase 5
    @_selected_item_id.setter
    def _selected_item_id(self, value: Optional[str]) -> None:
        self._queue_manager.selected_item_id = value

    # ponytail: remove in Phase 5
    @property
    def _total_count(self) -> int:
        return self._queue_manager.total_count

    # ponytail: remove in Phase 5
    @_total_count.setter
    def _total_count(self, value: int) -> None:
        self._queue_manager.total_count = value

    # ponytail: remove in Phase 5
    @property
    def _is_exporting(self) -> bool:
        if self._export_controller is not None:
            return self._export_controller.is_exporting
        return self._is_exporting_legacy

    # ponytail: remove in Phase 5
    @_is_exporting.setter
    def _is_exporting(self, value: bool) -> None:
        self._is_exporting_legacy = value
        if self._export_controller is not None:
            self._export_controller._is_exporting = value

    # ponytail: remove in Phase 5
    @property
    def _export_thread(self) -> Optional[threading.Thread]:
        if self._export_controller is not None:
            return self._export_controller.export_thread
        return None

    # ponytail: remove in Phase 5
    @_export_thread.setter
    def _export_thread(self, value: Optional[threading.Thread]) -> None:
        if self._export_controller is not None:
            self._export_controller._export_thread = value

    # ponytail: remove in Phase 5
    def _on_export_selected(self) -> None:
        if self._export_controller is not None:
            self._export_controller.on_export_selected()

    # ponytail: remove in Phase 5
    def _on_export_all(self, sync: bool = False) -> Optional[threading.Thread]:
        if self._export_controller is not None:
            return self._export_controller.on_export_all(sync=sync)
        return None

    # ponytail: remove in Phase 5
    def _reset_export_selected_button(self) -> None:
        if self._export_controller is not None:
            self._export_controller.reset_export_selected_button()

    # ponytail: remove in Phase 5
    def _reset_export_all_button(self) -> None:
        if self._export_controller is not None:
            self._export_controller.reset_export_all_button()

    # ponytail: remove in Phase 5
    def _get_selected_export_format(self) -> OutputFormat:
        if self._export_controller is not None:
            return self._export_controller.get_selected_export_format()
        return OutputFormat.BOTH

    # ponytail: remove in Phase 5
    @property
    def _last_applied_server_status(self) -> Optional[Tuple[ServerStatus, ServerOwnership]]:
        if getattr(self, "_server_controller", None) is not None:
            return self._server_controller.last_applied_server_status
        return self._legacy_last_applied_server_status

    # ponytail: remove in Phase 5
    @_last_applied_server_status.setter
    def _last_applied_server_status(self, value: Optional[Tuple[ServerStatus, ServerOwnership]]) -> None:
        self._legacy_last_applied_server_status = value
        if getattr(self, "_server_controller", None) is not None:
            self._server_controller.last_applied_server_status = value

    # ponytail: remove in Phase 5
    @property
    def _server_poller_thread(self) -> Optional[threading.Thread]:
        if getattr(self, "_server_controller", None) is not None:
            return self._server_controller.server_poller_thread
        return self._legacy_server_poller_thread

    # ponytail: remove in Phase 5
    @_server_poller_thread.setter
    def _server_poller_thread(self, value: Optional[threading.Thread]) -> None:
        self._legacy_server_poller_thread = value
        if getattr(self, "_server_controller", None) is not None:
            self._server_controller.server_poller_thread = value

    # ponytail: remove in Phase 5
    @property
    def _server_start_thread(self) -> Optional[threading.Thread]:
        if getattr(self, "_server_controller", None) is not None:
            return self._server_controller.server_start_thread
        return self._legacy_server_start_thread

    # ponytail: remove in Phase 5
    @_server_start_thread.setter
    def _server_start_thread(self, value: Optional[threading.Thread]) -> None:
        self._legacy_server_start_thread = value
        if getattr(self, "_server_controller", None) is not None:
            self._server_controller.server_start_thread = value

    # ponytail: remove in Phase 5
    @property
    def _server_stop_thread(self) -> Optional[threading.Thread]:
        if getattr(self, "_server_controller", None) is not None:
            return self._server_controller.server_stop_thread
        return self._legacy_server_stop_thread

    # ponytail: remove in Phase 5
    @_server_stop_thread.setter
    def _server_stop_thread(self, value: Optional[threading.Thread]) -> None:
        self._legacy_server_stop_thread = value
        if getattr(self, "_server_controller", None) is not None:
            self._server_controller.server_stop_thread = value

    # ponytail: remove in Phase 5
    def _apply_server_status_update(self, info: ServerStatusInfo) -> None:
        if getattr(self, "_server_controller", None) is not None:
            self._server_controller.apply_server_status_update(info)

    # ponytail: remove in Phase 5
    def _on_server_action_clicked(self) -> None:
        if getattr(self, "_server_controller", None) is not None:
            self._server_controller.on_server_action_clicked()

    # ponytail: remove in Phase 5
    def _start_server_poller(self) -> None:
        if getattr(self, "_server_controller", None) is not None:
            self._server_controller.start_poller()

    # ponytail: remove in Phase 5
    @property
    def _task_queue(self) -> queue.Queue[Optional[Path]]:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.task_queue
        return self._task_queue_backing

    # ponytail: remove in Phase 5
    @_task_queue.setter
    def _task_queue(self, value: queue.Queue[Optional[Path]]) -> None:
        self._task_queue_backing = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.task_queue = value

    # ponytail: remove in Phase 5
    @property
    def _result_queue(self) -> queue.Queue[WorkerEvent]:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.result_queue
        return self._result_queue_backing

    # ponytail: remove in Phase 5
    @_result_queue.setter
    def _result_queue(self, value: queue.Queue[WorkerEvent]) -> None:
        self._result_queue_backing = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.result_queue = value

    # ponytail: remove in Phase 5
    @property
    def _worker_thread(self) -> Optional[threading.Thread]:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.worker_thread
        return self._worker_thread_legacy

    # ponytail: remove in Phase 5
    @_worker_thread.setter
    def _worker_thread(self, value: Optional[threading.Thread]) -> None:
        self._worker_thread_legacy = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.worker_thread = value

    # ponytail: remove in Phase 5
    @property
    def _poll_id(self) -> Optional[str]:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.poll_id
        return self._poll_id_legacy

    # ponytail: remove in Phase 5
    @_poll_id.setter
    def _poll_id(self, value: Optional[str]) -> None:
        self._poll_id_legacy = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.poll_id = value

    # ponytail: remove in Phase 5
    @property
    def _current_cancel_event(self) -> Optional[threading.Event]:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.current_cancel_event
        return self._current_cancel_event_legacy

    # ponytail: remove in Phase 5
    @_current_cancel_event.setter
    def _current_cancel_event(self, value: Optional[threading.Event]) -> None:
        self._current_cancel_event_legacy = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.current_cancel_event = value

    # ponytail: remove in Phase 5
    @property
    def _pending_engine_settings(self) -> Optional[Settings]:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.pending_engine_settings
        return self._pending_engine_settings_legacy

    # ponytail: remove in Phase 5
    @_pending_engine_settings.setter
    def _pending_engine_settings(self, value: Optional[Settings]) -> None:
        self._pending_engine_settings_legacy = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.pending_engine_settings = value

    # ponytail: remove in Phase 5
    @property
    def _success_count(self) -> int:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.success_count
        return self._success_count_legacy

    # ponytail: remove in Phase 5
    @_success_count.setter
    def _success_count(self, value: int) -> None:
        self._success_count_legacy = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.success_count = value

    # ponytail: remove in Phase 5
    @property
    def _failed_count(self) -> int:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.failed_count
        return self._failed_count_legacy

    # ponytail: remove in Phase 5
    @_failed_count.setter
    def _failed_count(self, value: int) -> None:
        self._failed_count_legacy = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.failed_count = value

    # ponytail: remove in Phase 5
    @property
    def _progress_indeterminate(self) -> bool:
        if getattr(self, "_worker_coordinator", None) is not None:
            return self._worker_coordinator.progress_indeterminate
        return self._progress_indeterminate_legacy

    # ponytail: remove in Phase 5
    @_progress_indeterminate.setter
    def _progress_indeterminate(self, value: bool) -> None:
        self._progress_indeterminate_legacy = value
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.progress_indeterminate = value

    # ponytail: remove in Phase 5
    def _handle_worker_event(self, event: WorkerEvent) -> None:
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.handle_worker_event(event)

    # ponytail: remove in Phase 5
    def _process_result_queue(self) -> None:
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.process_result_queue()

    # ponytail: remove in Phase 5
    def _apply_pending_engine_settings(self) -> None:
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.apply_pending_engine_settings()

    # ponytail: remove in Phase 5
    def _on_cancel_current(self) -> None:
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.cancel_current()

    # ponytail: remove in Phase 5
    def _stop_indeterminate_progress(self) -> None:
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.stop_indeterminate_progress()

    # ponytail: remove in Phase 5
    def _worker_loop(self) -> None:
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.worker_loop()


    # ==========================================================================
    # UI Layout Construction
    # ==========================================================================

    def _build_layout(self) -> None:
        """Construct the top-level application layout."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header
        self.grid_rowconfigure(1, weight=1)  # Main Content
        self.grid_rowconfigure(2, weight=0)  # Footer

        self._build_header()
        self._build_body()
        self._build_footer()

    def _build_header(self) -> None:
        """Build the top header bar with title and backend status indicator."""
        header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=COLOR_SURFACE_1)
        header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        header_frame.grid_columnconfigure(0, weight=1)
        header_frame.grid_columnconfigure(1, weight=0)

        # App Title & Subtitle
        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w", padx=16, pady=8)

        title_label = ctk.CTkLabel(
            title_box,
            text="AksaraSight Local Studio",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        title_label.pack(side="left")

        version_badge = ctk.CTkLabel(
            title_box,
            text=f"v{__version__}",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        version_badge.pack(side="left", padx=(8, 0), pady=(3, 0))

        # Header Right Controls Container
        controls_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        controls_box.grid(row=0, column=1, sticky="e", padx=16, pady=8)

        # 1. Backend indicator badge
        if not self.settings.is_loopback:
            backend_str = f"REMOTE BACKEND: {self.settings.backend} ({self.settings.local_endpoint})"
            badge_fg = "#3d2a00"
            badge_text = COLOR_STATUS_PARTIAL
        else:
            backend_str = f"Backend: {self.settings.backend} ({self.settings.local_endpoint})"
            badge_fg = COLOR_INTERACTIVE_NEUTRAL
            badge_text = COLOR_TEXT_MUTED

        self._backend_badge = ctk.CTkLabel(
            controls_box,
            text=backend_str,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=badge_fg,
            text_color=badge_text,
            corner_radius=6,
            padx=10,
            pady=4,
        )
        self._backend_badge.pack(side="left", padx=(0, 8))

        # 2. Server Status Pill
        self._server_status_pill = ctk.CTkLabel(
            controls_box,
            text="● OFFLINE",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            text_color=COLOR_TEXT_MUTED,
            corner_radius=6,
            padx=10,
            pady=4,
        )
        self._server_status_pill.pack(side="left", padx=(0, 8))

        # 3. Server Action Button (Start / Stop)
        self._btn_server_action = ctk.CTkButton(
            controls_box,
            text="Start Server",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            width=90,
            height=28,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            command=self._on_server_action_clicked,
        )
        self._btn_server_action.pack(side="left", padx=(0, 8))

        # 4. Preferences / Settings Button
        self._btn_settings = ctk.CTkButton(
            controls_box,
            text="⚙ Preferences",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            width=105,
            height=28,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            command=self._open_settings_dialog,
        )
        self._btn_settings.pack(side="left", padx=(0, 0))

        # Server UI Controller
        self._server_controller = ServerUIController(
            server_manager=lambda: self.server_manager,
            settings=lambda: self.settings,
            engine=self.engine,
            safe_after=self._safe_after,
            is_shutting_down=lambda: self._is_shutting_down,
            shutdown_event=self._shutdown_event,
            update_footer=self._update_footer,
            server_status_pill=self._server_status_pill,
            btn_server_action=self._btn_server_action,
            format_error=_friendly_err,
        )
        if self._legacy_last_applied_server_status is not None:
            self._server_controller.last_applied_server_status = self._legacy_last_applied_server_status

    def _build_body(self) -> None:
        """Build the 2-column main body area."""
        body_frame = ctk.CTkFrame(self, fg_color="transparent")
        body_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(8, 4))
        body_frame.grid_columnconfigure(0, weight=38, minsize=320)
        body_frame.grid_columnconfigure(1, weight=62, minsize=460)
        body_frame.grid_rowconfigure(0, weight=1)

        self._build_left_panel(body_frame)
        self._build_right_panel(body_frame)

    def _build_left_panel(self, parent: ctk.CTkFrame) -> None:
        """Build the left panel: Drop zone card and Queue manager."""
        left_container = ctk.CTkFrame(parent, fg_color="transparent")
        left_container.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
        left_container.grid_columnconfigure(0, weight=1)
        left_container.grid_rowconfigure(0, weight=0)  # Drop zone
        left_container.grid_rowconfigure(1, weight=0)  # Queue header
        left_container.grid_rowconfigure(2, weight=1)  # Queue scroll list

        # Drop Zone Card (capped height ~116px, 16px padding, lighter surface)
        self._drop_zone = ctk.CTkFrame(
            left_container,
            corner_radius=8,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            fg_color=COLOR_SURFACE_1,
            cursor="hand2",
            height=116,
        )
        self._drop_zone.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 12))

        drop_inner = ctk.CTkFrame(self._drop_zone, fg_color="transparent")
        drop_inner.pack(padx=16, pady=16, fill="both", expand=True)

        dz_title = ctk.CTkLabel(
            drop_inner,
            text="Drop documents to extract",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLOR_TEXT_PRIMARY,
        )
        dz_title.pack()

        dz_subtitle = ctk.CTkLabel(
            drop_inner,
            text="or click anywhere in this card to browse local files",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        dz_subtitle.pack(pady=(2, 4))

        dz_formats = ctk.CTkLabel(
            drop_inner,
            text="PDF  ·  PNG  ·  JPG  ·  TIFF  ·  BMP  ·  WEBP",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        dz_formats.pack()

        # Bindings for Drop Zone (click and drag-and-drop)
        for widget in (self._drop_zone, drop_inner, dz_title, dz_subtitle, dz_formats):
            widget.bind("<Button-1>", lambda e: self._on_browse_files())

        # Drop zone hover feedback (brighten border on mouse enter)
        for hover_w in (self._drop_zone, drop_inner, dz_title, dz_subtitle, dz_formats):
            hover_w.bind("<Enter>", self._on_drop_zone_enter)
            hover_w.bind("<Leave>", self._on_drop_zone_leave)

        # Register drop target on drop zone card (tkinterdnd2 dynamically monkey-patches DnD methods onto tkinter.Widget at import time)
        self._drop_zone.drop_target_register(tkdnd.DND_FILES)  # type: ignore[missing-attribute]  # tkinterdnd2 dynamically monkey-patches Tkinter widgets at runtime
        self._drop_zone.dnd_bind("<<Drop>>", self._on_drop_files)  # type: ignore[missing-attribute]  # tkinterdnd2 dynamically monkey-patches Tkinter widgets at runtime

        # Drag-over visual feedback (amber border + tinted bg while dragging files over zone)
        self._drop_zone.dnd_bind("<<DropEnter>>", self._on_drag_enter)  # type: ignore[missing-attribute]  # tkinterdnd2 dynamically monkey-patches Tkinter widgets at runtime
        self._drop_zone.dnd_bind("<<DropLeave>>", self._on_drag_leave)  # type: ignore[missing-attribute]  # tkinterdnd2 dynamically monkey-patches Tkinter widgets at runtime

        # Queue Section Header (14px bold section header, tertiary clear button)
        queue_header = ctk.CTkFrame(left_container, fg_color="transparent")
        queue_header.grid(row=1, column=0, sticky="new", padx=0, pady=(0, 6))
        queue_header.grid_columnconfigure(0, weight=1)
        queue_header.grid_columnconfigure(1, weight=0)

        self._queue_title = ctk.CTkLabel(
            queue_header,
            text="Queue (0)",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._queue_title.grid(row=0, column=0, sticky="w")

        self._clear_btn = ctk.CTkButton(
            queue_header,
            text="Clear Finished",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            width=84,
            height=22,
            corner_radius=4,
            fg_color="transparent",
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_SUBTLE,
            command=self._on_clear_finished,
        )
        self._clear_btn.grid(row=0, column=1, sticky="e")

        self._queue_cleanup_hint = ctk.CTkLabel(
            queue_header,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#fbbf24",
            anchor="w",
        )

        # Scrollable Queue List
        self._queue_scroll = ctk.CTkScrollableFrame(
            left_container,
            corner_radius=6,
            fg_color=COLOR_SURFACE_2,
            scrollbar_button_color=COLOR_SCROLLBAR_THUMB,
            scrollbar_button_hover_color=COLOR_SCROLLBAR_THUMB_HOVER,
        )
        self._queue_scroll.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        left_container.grid_rowconfigure(2, weight=1)

        # Empty Queue Placeholder (compact centered block with monochrome geometric glyph)
        self._empty_queue_frame = ctk.CTkFrame(self._queue_scroll, fg_color="transparent")
        self._empty_queue_frame.pack(expand=True, pady=24)

        glyph = ctk.CTkLabel(
            self._empty_queue_frame,
            text="▤",
            font=ctk.CTkFont(family="Segoe UI Symbol", size=22),
            text_color=COLOR_TEXT_SUBTLE,
        )
        glyph.pack()

        eq_title = ctk.CTkLabel(
            self._empty_queue_frame,
            text="Queue is empty",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        eq_title.pack(pady=(4, 2))

        eq_hint = ctk.CTkLabel(
            self._empty_queue_frame,
            text="Drop files above or click to browse",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        eq_hint.pack()

        self._empty_queue_label = self._empty_queue_frame

    def _build_right_panel(self, parent: ctk.CTkFrame) -> None:
        """Build the right panel: Split preview pane tabview and action bar."""
        right_container = ctk.CTkFrame(parent, fg_color="transparent")
        right_container.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)
        right_container.grid_columnconfigure(0, weight=1)
        right_container.grid_rowconfigure(0, weight=1)  # Tabview
        right_container.grid_rowconfigure(1, weight=0)  # Progress Bar & Counter
        right_container.grid_rowconfigure(2, weight=0)  # Action Bar

        # Tabview styled as compact segmented control (~30px height, corner radius 6)
        self._tabview = ctk.CTkTabview(
            right_container,
            corner_radius=6,
            fg_color=COLOR_SURFACE_1,
            segmented_button_selected_color=COLOR_INTERACTIVE_NEUTRAL,
            segmented_button_selected_hover_color=COLOR_INTERACTIVE_HOVER,
            segmented_button_fg_color=COLOR_SURFACE_2,
            segmented_button_unselected_color=COLOR_SURFACE_2,
            segmented_button_unselected_hover_color=COLOR_INTERACTIVE_HOVER,
            command=self._on_tab_changed,
        )
        self._tabview._segmented_button.configure(
            height=30,
            corner_radius=6,
            border_width=0,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._tabview.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 6))

        tab_markdown = self._tabview.add("Raw Markdown")
        tab_preview = self._tabview.add("Text Preview")
        tab_image = self._tabview.add("Image Preview")
        tab_json = self._tabview.add("JSON Tree")
        align_segmented_button_corners(self._tabview._segmented_button, COLOR_CANVAS_BG)

        # Tab 1: Raw Markdown Textbox
        self._tb_markdown = ctk.CTkTextbox(
            tab_markdown,
            corner_radius=6,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            fg_color=COLOR_SURFACE_2,
            text_color=COLOR_TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
            scrollbar_button_color=COLOR_SCROLLBAR_THUMB,
            scrollbar_button_hover_color=COLOR_SCROLLBAR_THUMB_HOVER,
        )
        self._tb_markdown.pack(fill="both", expand=True, padx=4, pady=4)

        # Tab 2: Formatted Preview Textbox
        self._lbl_preview_disclaimer = ctk.CTkLabel(
            tab_preview,
            text="Preview applies light formatting — switch to Raw Markdown for exact output",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLOR_TEXT_SUBTLE,
            anchor="w",
        )
        self._lbl_preview_disclaimer.pack(side="bottom", fill="x", padx=6, pady=(0, 4))

        self._tb_preview = ctk.CTkTextbox(
            tab_preview,
            corner_radius=6,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            fg_color=COLOR_SURFACE_2,
            text_color=COLOR_TEXT_PRIMARY,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            wrap="word",
            scrollbar_button_color=COLOR_SCROLLBAR_THUMB,
            scrollbar_button_hover_color=COLOR_SCROLLBAR_THUMB_HOVER,
        )
        self._tb_preview.pack(side="top", fill="both", expand=True, padx=4, pady=(4, 2))

        # Configure rich markdown tags on underlying Tk text widget
        self._highlighter.configure_tags(self._tb_preview)

        # Tab 3: Image Preview with pagination controls and scrollable container
        self._image_preview = ImagePreviewController(
            preview_tab=tab_image,
            settings=self.settings,
            get_current_item=self._get_selected_queue_item,
        )
        self._img_nav_bar = self._image_preview.nav_bar
        self._btn_img_prev = self._image_preview.btn_prev
        self._lbl_img_page = self._image_preview.lbl_page
        self._btn_img_next = self._image_preview.btn_next
        self._lbl_img_info = self._image_preview.lbl_info
        self._img_scroll = self._image_preview.scroll_frame
        self._img_display_label = self._image_preview.display_label

        # Tab 4: JSON Tree Textbox
        self._tb_json = ctk.CTkTextbox(
            tab_json,
            corner_radius=6,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            fg_color=COLOR_SURFACE_2,
            text_color=COLOR_TEXT_PRIMARY,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="none",
            scrollbar_button_color=COLOR_SCROLLBAR_THUMB,
            scrollbar_button_hover_color=COLOR_SCROLLBAR_THUMB_HOVER,
        )
        self._tb_json.pack(fill="both", expand=True, padx=4, pady=4)

        # Initial Empty Text State
        self._set_textbox_content(
            self._tb_markdown,
            "<!-- No document selected -->\n<!-- Select an item from the queue on the left to inspect raw Markdown output -->",
        )
        self._render_markdown_preview(
            "Document Preview\n\nNo document selected. Drop or select a file to run local OCR.",
        )
        self._set_textbox_content(
            self._tb_json,
            '{\n  "status": "idle",\n  "message": "Select a document from the queue to inspect structured JSON output."\n}',
        )

        # Progress Bar & Counter Container
        progress_container = ctk.CTkFrame(right_container, fg_color="transparent")
        progress_container.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 6))
        progress_container.grid_columnconfigure(0, weight=1)
        progress_container.grid_columnconfigure(1, weight=0)

        self._lbl_progress_info = ctk.CTkLabel(
            progress_container,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._lbl_progress_info.grid(row=0, column=0, sticky="w", padx=2, pady=(0, 2))

        self._lbl_page_counter = ctk.CTkLabel(
            progress_container,
            text="Idle",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SECONDARY,
            anchor="e",
        )
        self._lbl_page_counter.grid(row=0, column=1, sticky="e", padx=2, pady=(0, 2))

        self._progress_bar = ctk.CTkProgressBar(
            progress_container,
            height=6,
            corner_radius=3,
            fg_color=COLOR_SURFACE_2,
            progress_color=COLOR_ACCENT_PRIMARY,
        )
        self._progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2, pady=0)
        self._progress_bar.set(0.0)

        # Action Bar with clear primary (slate blue) and secondary (neutral with border) weights
        action_bar = ctk.CTkFrame(right_container, fg_color="transparent")
        action_bar.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        action_bar.grid_columnconfigure(0, weight=0)
        action_bar.grid_columnconfigure(1, weight=1)
        action_bar.grid_columnconfigure(2, weight=0)
        action_bar.grid_columnconfigure(3, weight=0)
        action_bar.grid_columnconfigure(4, weight=0)

        self._btn_copy = ctk.CTkButton(
            action_bar,
            text="Copy to Clipboard",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            corner_radius=6,
            height=30,
            state="disabled",
            command=self._on_copy_clipboard,
        )
        self._btn_copy.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._btn_cancel = ctk.CTkButton(
            action_bar,
            text="Cancel (after current page)",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_SUBTLE,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            corner_radius=6,
            height=30,
            state="disabled",
            command=self._on_cancel_current,
        )
        self._btn_cancel.grid(row=0, column=1, sticky="w", padx=(0, 8))

        # Format Selector: Exactly 2 options: BOTH (default) vs DOCX
        self._opt_export_format = ctk.CTkOptionMenu(
            action_bar,
            values=[
                "Markdown & JSON (.md + .json)",
                "Word Document (.docx)",
            ],
            font=ctk.CTkFont(family="Segoe UI", size=11),
            dropdown_font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            button_color=COLOR_SURFACE_BORDER,
            button_hover_color=COLOR_INTERACTIVE_HOVER,
            dropdown_fg_color=COLOR_SURFACE_2,
            dropdown_hover_color=COLOR_INTERACTIVE_HOVER,
            dropdown_text_color=COLOR_TEXT_PRIMARY,
            text_color=COLOR_TEXT_PRIMARY,
            corner_radius=6,
            height=30,
            width=210,
            dynamic_resizing=False,
        )
        self._opt_export_format.set("Markdown & JSON (.md + .json)")
        self._opt_export_format.grid(row=0, column=2, sticky="e", padx=(0, 8))

        # Primary Button: Slate blue accent fill (starts disabled with neutral dark surface and border)
        self._btn_export_selected = ctk.CTkButton(
            action_bar,
            text="Export Selected",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT_SUBTLE,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            corner_radius=6,
            height=30,
            state="disabled",
            command=self._on_export_selected,
        )
        self._btn_export_selected.grid(row=0, column=3, sticky="e", padx=(0, 8))

        # Secondary Button: Neutral dark surface with border
        self._btn_export_all = ctk.CTkButton(
            action_bar,
            text="Export All",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            corner_radius=6,
            height=30,
            state="disabled",
            command=self._on_export_all,
        )
        self._btn_export_all.grid(row=0, column=4, sticky="e", padx=0)

        # Export Controller
        self._export_controller = ExportController(
            queue_manager=lambda: self._queue_manager,
            safe_after=self._safe_after,
            after=self.after,
            update_footer=self._update_footer,
            is_shutting_down=lambda: self._is_shutting_down,
            shutdown_event=self._shutdown_event,
            drain_ui_callbacks=self._drain_ui_callbacks,
            ask_directory=lambda *args, **kwargs: filedialog.askdirectory(*args, **kwargs),
            save_artifacts=lambda *a, **kw: save_artifacts(*a, **kw),
            resolve_unique_stem=lambda *a, **kw: resolve_unique_stem(*a, **kw),
            btn_export_selected=self._btn_export_selected,
            btn_export_all=self._btn_export_all,
            opt_export_format=self._opt_export_format,
            format_error=_friendly_err,
            on_action_buttons_changed=self._update_action_buttons,
        )

    def _build_footer(self) -> None:
        """Build the bottom status bar (~30px height) with trust indicator and counters."""
        footer_frame = ctk.CTkFrame(self, corner_radius=0, height=30, fg_color=COLOR_SURFACE_1)
        footer_frame.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        footer_frame.grid_columnconfigure(0, weight=1)
        footer_frame.grid_columnconfigure(1, weight=0)
        footer_frame.grid_columnconfigure(2, weight=0)

        # Left: Status indicator label
        self._footer_status = ctk.CTkLabel(
            footer_frame,
            text="Ready",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._footer_status.grid(row=0, column=0, sticky="w", padx=16, pady=(4, 5))
        self._status_label = self._footer_status

        # Center: Trust indicator badge
        trust_frame = ctk.CTkFrame(footer_frame, fg_color=COLOR_SURFACE_1)
        trust_frame.grid(row=0, column=1, sticky="nsew", padx=12, pady=(4, 5))

        trust_dot = ctk.CTkLabel(
            trust_frame,
            text="●",
            font=ctk.CTkFont(family="Segoe UI", size=9),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_STATUS_SUCCESS,
        )
        trust_dot.pack(side="left", padx=(0, 5))

        trust_label = ctk.CTkLabel(
            trust_frame,
            text="Local Processing — All data stays on your device",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_MUTED,
        )
        trust_label.pack(side="left")
        self._trust_label = trust_label

        # Right: Counters with numbers slightly brighter than the labels
        counters_frame = ctk.CTkFrame(footer_frame, fg_color=COLOR_SURFACE_1)
        counters_frame.grid(row=0, column=2, sticky="e", padx=16, pady=(4, 5))

        lbl_tot = ctk.CTkLabel(
            counters_frame,
            text="Total: ",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_SUBTLE,
        )
        lbl_tot.pack(side="left")

        self._lbl_total_val = ctk.CTkLabel(
            counters_frame,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._lbl_total_val.pack(side="left", padx=(0, 10))

        lbl_succ = ctk.CTkLabel(
            counters_frame,
            text="Success: ",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_SUBTLE,
        )
        lbl_succ.pack(side="left")

        self._lbl_success_val = ctk.CTkLabel(
            counters_frame,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._lbl_success_val.pack(side="left", padx=(0, 10))

        lbl_fail = ctk.CTkLabel(
            counters_frame,
            text="Failed: ",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_SUBTLE,
        )
        lbl_fail.pack(side="left")

        self._lbl_failed_val = ctk.CTkLabel(
            counters_frame,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLOR_SURFACE_1,
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._lbl_failed_val.pack(side="left")

        self._footer_counters = counters_frame

    # ==========================================================================
    # Queue Management & Selection
    # ==========================================================================

    def enqueue_file(self, file_path: Union[str, Path], sync: bool = False) -> Optional[threading.Thread]:
        """Submit a document file or folder to the worker task queue and add it to the UI queue table."""
        return self._queue_manager.enqueue_file(file_path, sync=sync)

    def wait_for_ingest(self, timeout: float = 5.0) -> None:
        """Wait for any active background folder scan and pending UI insertion batches."""
        self._queue_manager.wait_for_ingest(timeout=timeout)

    # ponytail: remove in Phase 5
    def _format_queue_item_meta(self, item: QueueItem) -> str:
        return self._queue_manager.format_item_meta(item)

    # ponytail: remove in Phase 5
    def _select_queue_item(self, item_id: str) -> None:
        self._queue_manager.select_item(item_id)

    def _on_tab_changed(self) -> None:
        """Render the newly active tab on-demand for the currently selected item."""
        if self._selected_item_id and self._selected_item_id in self._queue_items:
            self._render_preview(self._queue_items[self._selected_item_id])

    def select_tab(self, tab_name: str) -> None:
        """Select a preview tab programmatically and trigger on-demand rendering."""
        self._tabview.set(tab_name)
        self._on_tab_changed()

    def _render_preview(self, item: QueueItem, tab_name: Optional[str] = None) -> None:
        """Populate the active preview tab based on the queue item's status and results."""
        target_tab = tab_name or self._tabview.get()

        if target_tab == "Image Preview":
            self._render_image_preview(item)
            self._update_action_buttons()
            return

        if item.status == QueueItemStatus.QUEUED:
            if target_tab == "Raw Markdown":
                md_text = f"[{item.file_path.name} is queued for processing... waiting for worker thread]"
                self._set_textbox_content(self._tb_markdown, md_text)
            elif target_tab == "Text Preview":
                prev_text = (
                    f"Document Queued: {item.file_path.name}\n\n"
                    "This document is waiting in the queue. Processing will begin automatically."
                )
                self._render_markdown_preview(prev_text)
            elif target_tab == "JSON Tree":
                json_text = json.dumps(
                    {"status": "QUEUED", "file": item.file_path.name},
                    indent=2,
                )
                self._set_textbox_content(self._tb_json, json_text)

        elif item.status == QueueItemStatus.PROCESSING:
            if item.result and item.result.pages:
                md = item.result.markdown
                if target_tab == "Raw Markdown":
                    self._set_textbox_content(self._tb_markdown, md)
                elif target_tab == "Text Preview":
                    self._render_markdown_preview(md)
                elif target_tab == "JSON Tree":
                    self._set_textbox_content(self._tb_json, item.result.to_json())
            else:
                if target_tab == "Raw Markdown":
                    md_text = f"[{item.file_path.name} is currently being processed by AksaraSight (GLM-OCR)...]"
                    self._set_textbox_content(self._tb_markdown, md_text)
                elif target_tab == "Text Preview":
                    prev_text = (
                        f"Processing Document: {item.file_path.name}\n\n"
                        "Extracting and rasterizing pages, dispatching inference requests to local backend."
                    )
                    self._render_markdown_preview(prev_text)
                elif target_tab == "JSON Tree":
                    json_text = json.dumps(
                        {"status": "PROCESSING", "file": item.file_path.name},
                        indent=2,
                    )
                    self._set_textbox_content(self._tb_json, json_text)

        elif item.status == QueueItemStatus.FAILED:
            err_msg = item.error or (item.result.error if item.result else "Unknown processing failure")
            if target_tab == "Raw Markdown":
                md_text = f"Error processing {item.file_path.name}:\n\n{err_msg}"
                self._set_textbox_content(self._tb_markdown, md_text)
            elif target_tab == "Text Preview":
                prev_text = f"Processing Failed: {item.file_path.name}\n\nError:\n{err_msg}"
                self._render_markdown_preview(prev_text)
            elif target_tab == "JSON Tree":
                json_text = item.result.to_json() if item.result else json.dumps(
                    {"status": "FAILED", "file": item.file_path.name, "error": err_msg},
                    indent=2,
                )
                self._set_textbox_content(self._tb_json, json_text)

        elif item.status == QueueItemStatus.CANCELLED:
            cancel_msg = item.error or (item.result.error if item.result else "Processing cancelled by user")
            if target_tab == "Raw Markdown":
                if item.result and item.result.pages:
                    md_text = f"<!-- Cancelled: {cancel_msg} -->\n\n" + item.result.markdown
                else:
                    md_text = f"<!-- Processing cancelled before pages completed -->\n\n{cancel_msg}"
                self._set_textbox_content(self._tb_markdown, md_text)
            elif target_tab == "Text Preview":
                if item.result and item.result.pages:
                    prev_text = f"Processing Cancelled: {item.file_path.name}\n({cancel_msg})\n\nPartial Output:\n" + item.result.markdown
                else:
                    prev_text = f"Processing Cancelled: {item.file_path.name}\n\n{cancel_msg}"
                self._render_markdown_preview(prev_text)
            elif target_tab == "JSON Tree":
                json_text = item.result.to_json() if item.result else json.dumps(
                    {"status": "CANCELLED", "file": item.file_path.name, "error": cancel_msg},
                    indent=2,
                )
                self._set_textbox_content(self._tb_json, json_text)

        else:  # SUCCESS / PARTIAL
            if item.result is None:
                raise RuntimeError(f"Queue item {item.item_id} has status {item.status.name} but missing OCRResult")
            md = item.result.markdown
            if target_tab == "Raw Markdown":
                self._set_textbox_content(self._tb_markdown, md)
            elif target_tab == "Text Preview":
                self._render_markdown_preview(md)
            elif target_tab == "JSON Tree":
                self._set_textbox_content(self._tb_json, item.result.to_json())

        self._update_action_buttons()

    def _render_markdown_preview(self, raw_text: str) -> None:
        """Render markdown in _tb_preview with rich typography tags.

        Gracefully degrades to plain text without crashing if parsing fails or input is malformed.
        """
        self._set_textbox_content(self._tb_preview, raw_text)

        try:
            self._highlighter.apply_tags(self._tb_preview)
        except Exception as exc:
            # Graceful degradation fallback: clear tags and retain plain text
            logger.warning("Markdown tag rendering error, falling back to plain text: %s", exc)
            self._highlighter.clear_tags(self._tb_preview)

    def _clear_preview_tags(self) -> None:
        """Remove all formatting tags from the preview text widget."""
        self._highlighter.clear_tags(self._tb_preview)

    def _apply_markdown_tags(self) -> None:
        """Parse text in _tb_preview and apply typography tags."""
        self._highlighter.apply_tags(self._tb_preview)

    def _get_selected_queue_item(self) -> Optional[QueueItem]:
        """Return the currently selected QueueItem, if any."""
        if self._selected_item_id and self._selected_item_id in self._queue_items:
            return self._queue_items[self._selected_item_id]
        return None

    def _load_image_page_on_demand(
        self,
        file_path: Path,
        page_index: int = 0,
        effective_dpi: Optional[int] = None,
    ) -> Tuple[Optional[Image.Image], Optional[str]]:
        """Load and rasterize a single page on-demand via ImagePreviewController."""
        if self._image_preview is not None:
            return self._image_preview.load_page(file_path, page_index=page_index, effective_dpi=effective_dpi)
        effective_dpi = effective_dpi or getattr(self.settings, "dpi", 100) or 100
        try:
            raw_bytes = rasterize_page(file_path, page_idx=page_index, dpi=effective_dpi)
            pil_img = Image.open(io.BytesIO(raw_bytes))
            pil_img.load()
            return pil_img, None
        except PipelineError as exc:
            return None, f"Failed to load image preview: {exc}"
        except Exception as exc:
            return None, f"Failed to load image preview: {exc}"

    def _render_image_preview(self, item: QueueItem) -> None:
        """Render original raster scan image for the active document page on-demand."""
        if self._image_preview is not None:
            self._image_preview.render(item)

    def _reset_image_preview(self) -> None:
        """Reset the image preview controls and canvas to empty state."""
        if self._image_preview is not None:
            self._image_preview.reset()

    def _on_img_prev(self) -> None:
        """Navigate to the previous page in Image Preview."""
        if self._image_preview is not None:
            self._image_preview.on_prev(self._get_selected_queue_item())

    def _on_img_next(self) -> None:
        """Navigate to the next page in Image Preview."""
        if self._image_preview is not None:
            self._image_preview.on_next(self._get_selected_queue_item())

    def _set_textbox_content(self, textbox: ctk.CTkTextbox, content: str) -> None:
        """Safely update text in a read-only CTkTextbox."""
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", content)
        textbox.configure(state="disabled")

    def _update_action_buttons(self) -> None:
        """Update state of Action Bar buttons based on selected and available items."""
        selected_item = (
            self._queue_items.get(self._selected_item_id)
            if self._selected_item_id is not None
            else None
        )
        has_selected = selected_item is not None
        selected_completed = (
            selected_item is not None
            and selected_item.status in (QueueItemStatus.SUCCESS, QueueItemStatus.CANCELLED)
            and selected_item.result is not None
            and len(selected_item.result.pages) > 0
        )

        completed_count = sum(
            1
            for it in self._queue_items.values()
            if it.status == QueueItemStatus.SUCCESS and it.result is not None
        )

        # Cancel button state: active only when a job is actively processing and cancel not yet requested
        is_processing = any(
            it.status == QueueItemStatus.PROCESSING
            for it in self._queue_items.values()
        )
        if is_processing and self._current_cancel_event and not self._current_cancel_event.is_set():
            self._btn_cancel.configure(text="Cancel (after current page)", state="normal")
        elif is_processing and self._current_cancel_event and self._current_cancel_event.is_set():
            self._btn_cancel.configure(text="Cancelling...", state="disabled")
        else:
            self._btn_cancel.configure(text="Cancel (after current page)", state="disabled")

        self._btn_copy.configure(state="normal" if selected_completed else "disabled")

        if self._export_controller is not None:
            self._export_controller.update_buttons(
                selected_completed=selected_completed,
                completed_count=completed_count,
            )

    # ponytail: remove in Phase 5
    def _update_queue_header(self) -> None:
        """Update the queue header label with active total count and cleanup hint."""
        self._queue_manager.update_header()

    def _update_footer(self, message: Optional[str] = None) -> None:
        """Update the footer status message and counters."""
        if message:
            self._footer_status.configure(text=message)
        self._lbl_total_val.configure(text=str(self._total_count))
        self._lbl_success_val.configure(text=str(self._success_count))
        self._lbl_failed_val.configure(text=str(self._failed_count))

    # ==========================================================================
    # Action Bar Handlers
    # ==========================================================================

    def _on_copy_clipboard(self) -> None:
        """Copy active markdown text of selected item to Windows clipboard."""
        if not self._selected_item_id or self._selected_item_id not in self._queue_items:
            return

        item = self._queue_items[self._selected_item_id]
        if not item.result:
            return

        markdown_text = item.result.markdown
        self.clipboard_clear()
        self.clipboard_append(markdown_text)

        # Temporary visual feedback
        self._btn_copy.configure(text="Copied!")
        self.after(1200, lambda: self._btn_copy.configure(text="Copy to Clipboard"))

    def wait_for_export(self, timeout: float = 3.0) -> None:
        """Wait for any active background export thread to complete and drain main loop callbacks."""
        if self._export_controller is not None:
            self._export_controller.wait_for_export(timeout=timeout)
        else:
            if self._export_thread and self._export_thread.is_alive():
                self._export_thread.join(timeout=timeout)
            self._drain_ui_callbacks()
            try:
                self.update()
            except Exception:
                pass

    def _on_queue_emptied(self) -> None:
        """Reset preview and status displays when all finished items are cleared and queue is empty."""
        self._set_textbox_content(
            self._tb_markdown,
            "<!-- No document selected -->\n<!-- Select an item from the queue on the left to inspect raw Markdown output -->",
        )
        self._render_markdown_preview(
            "Document Preview\n\nNo document selected. Drop or select a file to run local OCR.",
        )
        self._set_textbox_content(
            self._tb_json,
            '{\n  "status": "idle",\n  "message": "Select a document from the queue to inspect structured JSON output."\n}',
        )
        self._reset_image_preview()
        self._progress_bar.set(0.0)
        self._lbl_page_counter.configure(text="Idle")
        self._lbl_progress_info.configure(text="")
        if self._empty_queue_label.winfo_manager() != "pack":
            self._empty_queue_label.pack(expand=True, pady=24)

    # ponytail: remove in Phase 5
    def _on_clear_finished(self) -> None:
        """Remove completed and failed items from the queue, keeping pending/active ones."""
        self._queue_manager.clear_finished()

    def _on_browse_files(self) -> None:
        """Open native Windows file picker dialog and enqueue selected files."""
        file_types = [
            ("Supported Documents", "*.pdf;*.png;*.jpg;*.jpeg;*.tiff;*.tif;*.bmp;*.webp"),
            ("PDF Documents", "*.pdf"),
            ("Images", "*.png;*.jpg;*.jpeg;*.tiff;*.tif;*.bmp;*.webp"),
            ("All Files", "*.*"),
        ]
        selected_paths = filedialog.askopenfilenames(
            title="Select Documents for AksaraSight",
            filetypes=file_types,
        )
        for p in selected_paths:
            self.enqueue_file(p)

    def _on_drop_files(self, event: Any) -> None:
        """Handle native drop events received from TkinterDnD."""
        raw_data = getattr(event, "data", "")
        if not raw_data:
            return

        try:
            file_paths = self.tk.splitlist(raw_data)
        except Exception as exc:
            sys.stderr.write(f"Failed to parse dropped files data: {exc}\n")
            return

        for path_str in file_paths:
            path = Path(path_str)
            print(f"[GUI DnD] Dropped file received: {path}")
            self.enqueue_file(path)

    def _on_drop_zone_enter(self, event: Any = None) -> None:
        """Brighten drop zone border on mouse enter."""
        self._drop_zone.configure(border_color=COLOR_SURFACE_BORDER_HOVER)

    def _on_drop_zone_leave(self, event: Any = None) -> None:
        """Revert drop zone border to default on mouse leave."""
        self._drop_zone.configure(border_color=COLOR_SURFACE_BORDER)

    def _on_drag_enter(self, event: Any = None) -> Any:
        """Visual feedback when dragging files over the drop zone (accent border + tinted bg)."""
        self._drop_zone.configure(border_color=COLOR_ACCENT_PRIMARY, fg_color=COLOR_DRAGOVER_BG)
        return getattr(event, "action", None)

    def _on_drag_leave(self, event: Any = None) -> Any:
        """Restore default drop zone appearance when drag leaves."""
        self._drop_zone.configure(border_color=COLOR_SURFACE_BORDER, fg_color=COLOR_SURFACE_1)
        return getattr(event, "action", None)

    # ponytail: remove in Phase 5
    def _on_queue_row_enter(self, event: Any = None, item_id: str = "") -> None:
        """Lighten row background on mouse enter, unless already selected."""
        self._queue_manager._on_row_enter(event, item_id)

    # ponytail: remove in Phase 5
    def _on_queue_row_leave(self, event: Any = None, item_id: str = "") -> None:
        """Restore row background on mouse leave, unless already selected."""
        self._queue_manager._on_row_leave(event, item_id)

    # ==========================================================================
    # Server Lifecycle & Preferences Management
    # ==========================================================================

    def _drain_ui_callbacks(self) -> None:
        """Drain and execute callbacks queued from background threads on the main UI thread."""
        while not self._ui_callback_queue.empty():
            try:
                func, args, kwargs = self._ui_callback_queue.get_nowait()
            except queue.Empty:
                break
            try:
                func(*args, **kwargs)
            except Exception as exc:
                logger.warning("Error executing UI callback: %s", exc)

    def _safe_after(self, ms: int, func: Any, *args: Any, **kwargs: Any) -> None:
        """Safely schedule a callback on Tk main loop or queue if window is not closing."""
        if self._is_shutting_down or self._shutdown_event.is_set():
            return
        if threading.current_thread() is threading.main_thread():
            try:
                self.after(ms, func, *args)
            except Exception:
                pass
        else:
            self._ui_callback_queue.put((func, args, kwargs))



    def _open_settings_dialog(self) -> None:
        """Open the modal Preferences and Serving Configuration dialog."""
        if self._settings_window is not None:
            try:
                if self._settings_window.winfo_exists():
                    self._settings_window.focus()
                    return
            except Exception:
                pass

        win = SettingsWindow(
            self,
            settings=self.settings,
            server_manager=self.server_manager,
            on_save_callback=self._on_settings_saved,
        )
        self._settings_window = win

    def _on_settings_saved(self, new_settings: Settings) -> None:
        """Callback invoked when preferences are updated and saved in SettingsWindow."""
        self.settings = new_settings
        self.server_manager.settings = new_settings

        # Queue settings for safe inter-document update
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.queue_pending_settings(new_settings)
        else:
            self._pending_engine_settings = new_settings
            if hasattr(self.engine, "invalidate_backend_verification"):
                self.engine.invalidate_backend_verification()
            if self._current_cancel_event is None:
                self._apply_pending_engine_settings()

        # Refresh queue rows' metadata if DPI setting changed
        for q_item in self._queue_items.values():
            if q_item.detail_label and q_item.status in (QueueItemStatus.SUCCESS, QueueItemStatus.CANCELLED):
                q_item.detail_label.configure(text=self._format_queue_item_meta(q_item))

        # Update header backend badge
        if not self.settings.is_loopback:
            backend_str = f"REMOTE BACKEND: {self.settings.backend} ({self.settings.local_endpoint})"
            badge_fg = "#3d2a00"
            badge_text = COLOR_STATUS_PARTIAL
        else:
            backend_str = f"Backend: {self.settings.backend} ({self.settings.local_endpoint})"
            badge_fg = COLOR_INTERACTIVE_NEUTRAL
            badge_text = COLOR_TEXT_MUTED

        self._backend_badge.configure(
            text=backend_str,
            fg_color=badge_fg,
            text_color=badge_text,
        )

        self._update_footer("Preferences saved.")

        # Immediate status poll to reflect any endpoint or server changes
        def _poll_now():
            info = self.server_manager.poll_status()
            self._safe_after(0, self._apply_server_status_update, info)

        threading.Thread(target=_poll_now, daemon=True).start()

    def show_restart_required_banner(self) -> None:
        """Display notice that server configuration changed and requires restart."""
        self._update_footer("⚠ Server settings changed. Stop and Start the server to apply changes.")

    def _on_closing(self) -> None:
        """Cleanly terminate background worker, network sessions, and destroy window."""
        if self._is_shutting_down:
            return
        self._is_shutting_down = True

        # 1. Signal worker thread and server poller to stop
        self._shutdown_event.set()

        # 2. Worker shutdown via coordinator (cancels poll timer, drains tasks, sends sentinel, joins worker)
        if getattr(self, "_worker_coordinator", None) is not None:
            self._worker_coordinator.shutdown(timeout=1.0)
        else:
            if self._poll_id is not None:
                try:
                    self.after_cancel(self._poll_id)
                except Exception:
                    pass
                self._poll_id = None

            while not self._task_queue.empty():
                try:
                    self._task_queue.get_nowait()
                    self._task_queue.task_done()
                except (queue.Empty, ValueError):
                    break

            try:
                self._task_queue.put_nowait(None)
            except (queue.Full, ValueError):
                pass

            if self._worker_thread and self._worker_thread.is_alive():
                self._worker_thread.join(timeout=1.0)

        # 4b. Join export thread if running
        if hasattr(self, "_export_thread") and self._export_thread is not None and self._export_thread.is_alive():
            self._export_thread.join(timeout=1.0)

        # 4c. Join ingest threads if running
        if self._queue_manager is not None:
            for t in self._queue_manager.ingest_threads:
                if t.is_alive():
                    t.join(timeout=0.5)

        # 4d. Join runtime download thread if running
        if hasattr(self, "_runtime_download_thread") and self._runtime_download_thread is not None and self._runtime_download_thread.is_alive():
            self._runtime_download_thread.join(timeout=1.0)

        # 5. Join server poller and worker threads via ServerUIController
        if hasattr(self, "_server_controller") and self._server_controller is not None:
            self._server_controller.shutdown(timeout=1.0)
        else:
            if hasattr(self, "_server_poller_thread") and self._server_poller_thread is not None:
                if self._server_poller_thread.is_alive():
                    self._server_poller_thread.join(timeout=1.0)
            if hasattr(self, "_server_stop_thread") and self._server_stop_thread is not None:
                if self._server_stop_thread.is_alive():
                    self._server_stop_thread.join(timeout=1.0)
            if hasattr(self, "_server_start_thread") and self._server_start_thread is not None:
                if self._server_start_thread.is_alive():
                    self._server_start_thread.join(timeout=1.0)

        # 6. Stop managed server and close server manager
        try:
            if hasattr(self, "server_manager") and self.server_manager is not None:
                if getattr(self.server_manager, "is_managed", False):
                    logger.info("Stopping managed server process on application exit...")
                    self.server_manager.stop()
                self.server_manager.shutdown()
        except Exception as sm_exc:
            sys.stderr.write(f"Warning: error shutting down server manager: {sm_exc}\n")

        # 7. Explicitly close VisionClient / network sessions
        try:
            if hasattr(self.engine, "close"):
                self.engine.close()
            elif hasattr(self.engine, "client") and hasattr(self.engine.client, "close"):
                self.engine.client.close()
        except Exception as close_exc:
            sys.stderr.write(f"Warning: error closing engine client: {close_exc}\n")

        # 8. Destroy modal settings window if open
        if hasattr(self, "_settings_window") and self._settings_window is not None:
            try:
                self._settings_window.destroy()
            except Exception:
                pass

        # 9. Flush pending idle tasks and destroy window
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.destroy()


def _setup_frozen_logging() -> Optional[Path]:
    """Configure file-based logging when running as a frozen executable.

    Only active when running inside a PyInstaller frozen bundle
    (getattr(sys, 'frozen', False) is True). Captures unhandled
    exceptions via sys.excepthook to %LOCALAPPDATA%\\AksaraSight\\logs\\app.log.
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        app_data = os.environ.get("LOCALAPPDATA")
        base_dir = Path(app_data) if app_data else (Path.home() / "AppData" / "Local")
        log_dir = base_dir / "AksaraSight" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"

        handler = logging.FileHandler(str(log_file), encoding="utf-8", mode="a")
        formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
        handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

        def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            logging.getLogger("crash").critical(
                "Unhandled exception in frozen GUI runtime",
                exc_info=(exc_type, exc_value, exc_traceback),
            )

        sys.excepthook = _handle_unhandled_exception
        logging.getLogger("app").info("Frozen application started (v%s)", __version__)
        return log_file
    except Exception:
        return None


def main() -> None:
    """Run the AksaraSight Local GUI application."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print("AksaraSight Local Studio Desktop GUI")
        print("Usage: python -m gui.app")
        return
    _setup_frozen_logging()
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("aksarasight.localstudio.gui.1.0")
        except Exception:
            pass
    app = OCRApp()
    try:
        app.mainloop()
    finally:
        app._on_closing()


if __name__ == "__main__":
    main()
