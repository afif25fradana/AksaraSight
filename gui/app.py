"""GUI Application for OCR-LLM-Local desktop studio."""

import base64
from dataclasses import dataclass, field
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
from typing import Any, Dict, List, Optional, Set, Union

import customtkinter as ctk
from PIL import Image
import tkinterdnd2 as tkdnd
import tkinterdnd2.TkinterDnD as tdnd

import pypdfium2 as pdfium

from config.settings import Settings
from core.constants import SUPPORTED_EXTENSIONS, __version__
from core.engine import OCREngine
from core.formatter import format_output, resolve_unique_stem, save_artifacts
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat, PageResult
from core.pipeline import _PDFIUM_LOCK
from core.server_manager import ServerManager, ServerOwnership, ServerStatus, ServerStatusInfo
# Design System Tokens - Calm Trust Palette (WCAG 2.1 AA verified)
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
)

from gui.settings_window import SettingsWindow

logger = logging.getLogger(__name__)


class WorkerEventType(str, Enum):
    """Event types posted from the background worker thread to the main UI thread."""
    STARTED = "STARTED"
    PAGE_PROGRESS = "PAGE_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    WORKER_CRASHED = "WORKER_CRASHED"


class QueueItemStatus(str, Enum):
    """Status states for items in the document queue."""
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class WorkerEvent:
    """Structured event emitted by the worker thread across the result queue."""
    event_type: WorkerEventType
    file_path: str
    result: Optional[OCRResult] = None
    error: Optional[str] = None
    current_page: int = 0
    total_pages: int = 0
    page_result: Optional[PageResult] = None
    processed_dpi: Optional[int] = None


@dataclass
class QueueItem:
    """State model for a document item tracked in the UI queue manager."""
    item_id: str
    file_path: Path
    status: QueueItemStatus = QueueItemStatus.QUEUED
    duration: float = 0.0
    result: Optional[OCRResult] = None
    error: Optional[str] = None
    file_size_str: Optional[str] = None
    processed_dpi: Optional[int] = None
    # UI references
    row_frame: Optional[ctk.CTkFrame] = None
    indicator_bar: Optional[ctk.CTkFrame] = None
    chip_label: Optional[ctk.CTkLabel] = None
    badge_label: Optional[ctk.CTkLabel] = None
    name_label: Optional[ctk.CTkLabel] = None
    detail_label: Optional[ctk.CTkLabel] = None


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
    """GLM-OCR Local desktop studio application window.

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
        self._server_poller_thread: Optional[threading.Thread] = None

        # Window appearance and geometry
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=COLOR_CANVAS_BG)
        self.title("GLM-OCR Local Studio")
        for candidate in [
            Path(__file__).parent / "assets" / "icon.ico",
            Path(sys.executable).parent / "_internal" / "gui" / "assets" / "icon.ico",
            Path(sys.executable).parent / "assets" / "icon.ico",
        ]:
            if candidate.is_file():
                try:
                    self.iconbitmap(str(candidate))
                    break
                except Exception:
                    pass
        self.geometry("1020x680")
        self.minsize(820, 520)

        # Thread synchronization queues and state
        self._task_queue: queue.Queue[Optional[Path]] = queue.Queue()
        self._result_queue: queue.Queue[WorkerEvent] = queue.Queue()
        self._shutdown_event = threading.Event()
        self._is_shutting_down = False
        self._poll_id: Optional[str] = None

        # Queue items state tracking
        self._queue_items: Dict[str, QueueItem] = {}
        self._selected_item_id: Optional[str] = None
        self._total_count: int = 0
        self._success_count: int = 0
        self._failed_count: int = 0
        self._current_cancel_event: Optional[threading.Event] = None
        self._pending_engine_settings: Optional[Settings] = None
        self._current_image_page_idx: int = 0
        self._current_ctk_image: Optional[ctk.CTkImage] = None
        self._progress_indeterminate: bool = False
        self._last_applied_server_status: Optional[Tuple[ServerStatus, ServerOwnership]] = None
        self._is_exporting: bool = False
        self._export_thread: Optional[threading.Thread] = None
        self._runtime_download_thread: Optional[threading.Thread] = None
        self._ingest_threads: List[threading.Thread] = []
        self._pending_batch_inserts: int = 0
        self._ui_callback_queue: queue.Queue[Tuple[Any, tuple, dict]] = queue.Queue()

        # Build UI layout
        self._build_layout()

        # Auto-start managed server if enabled in settings and offline
        if self.settings.auto_start_server:
            try:
                init_info = self.server_manager.poll_status()
                if init_info.status == ServerStatus.OFFLINE:
                    logger.info("auto_start_server enabled; starting backend server process...")
                    self.server_manager.start()
            except Exception as auto_start_err:
                logger.warning("Failed to auto-start backend server on launch: %s", auto_start_err)

        # Start periodic server health poller
        self._start_server_poller()

        # Protocol handlers
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Background worker thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="OCRWorkerThread",
            daemon=True,
        )
        self._worker_thread.start()

        # Start periodic result queue polling
        self._process_result_queue()

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
            text="GLM-OCR Local Studio",
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

        # Register drop target on drop zone card
        self._drop_zone.drop_target_register(tkdnd.DND_FILES)
        self._drop_zone.dnd_bind("<<Drop>>", self._on_drop_files)

        # Drag-over visual feedback (amber border + tinted bg while dragging files over zone)
        self._drop_zone.dnd_bind("<<DropEnter>>", self._on_drag_enter)
        self._drop_zone.dnd_bind("<<DropLeave>>", self._on_drag_leave)

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
        tw = self._tb_preview._textbox
        tw.tag_config("h1", font=("Segoe UI", 15, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("h2", font=("Segoe UI", 13, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("h3", font=("Segoe UI", 12, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("bold", font=("Segoe UI", 12, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("italic", font=("Segoe UI", 12, "italic"), foreground=COLOR_TEXT_SECONDARY)
        tw.tag_config("code_inline", font=("Consolas", 11), foreground=COLOR_ACCENT_TEXT, background=COLOR_SURFACE_1)
        tw.tag_config("code_block", font=("Consolas", 11), foreground=COLOR_TEXT_PRIMARY, background=COLOR_SURFACE_1)
        tw.tag_config("table_header", font=("Consolas", 11, "bold"), foreground=COLOR_ACCENT_TEXT, background=COLOR_SURFACE_1)
        tw.tag_config("table_row", font=("Consolas", 11), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("bullet", font=("Segoe UI", 12), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("divider", foreground=COLOR_SURFACE_BORDER)
        tw.tag_config("muted", foreground=COLOR_TEXT_MUTED)

        # Tab 3: Image Preview with pagination controls and scrollable container
        self._img_nav_bar = ctk.CTkFrame(tab_image, fg_color=COLOR_SURFACE_1, height=36, corner_radius=6)
        self._img_nav_bar.pack(fill="x", padx=4, pady=(4, 6))
        self._img_nav_bar.grid_columnconfigure(0, weight=0)
        self._img_nav_bar.grid_columnconfigure(1, weight=0)
        self._img_nav_bar.grid_columnconfigure(2, weight=0)
        self._img_nav_bar.grid_columnconfigure(3, weight=1)
        self._img_nav_bar.grid_columnconfigure(4, weight=0)

        self._btn_img_prev = ctk.CTkButton(
            self._img_nav_bar,
            text="◀ Prev",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            width=65,
            height=26,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            state="disabled",
            command=self._on_img_prev,
        )
        self._btn_img_prev.grid(row=0, column=0, padx=(6, 4), pady=4)

        self._lbl_img_page = ctk.CTkLabel(
            self._img_nav_bar,
            text="Page 0 of 0",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._lbl_img_page.grid(row=0, column=1, padx=6, pady=4)

        self._btn_img_next = ctk.CTkButton(
            self._img_nav_bar,
            text="Next ▶",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            width=65,
            height=26,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            state="disabled",
            command=self._on_img_next,
        )
        self._btn_img_next.grid(row=0, column=2, padx=(4, 6), pady=4)

        self._lbl_img_info = ctk.CTkLabel(
            self._img_nav_bar,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
        )
        self._lbl_img_info.grid(row=0, column=4, padx=10, pady=4, sticky="e")

        self._img_scroll = ctk.CTkScrollableFrame(
            tab_image,
            corner_radius=6,
            fg_color=COLOR_SURFACE_2,
            scrollbar_button_color=COLOR_SCROLLBAR_THUMB,
            scrollbar_button_hover_color=COLOR_SCROLLBAR_THUMB_HOVER,
        )
        self._img_scroll.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self._img_display_label = ctk.CTkLabel(
            self._img_scroll,
            text="No image preview available for this document.\nProcess a document to inspect scan raster.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        self._img_display_label.pack(expand=True, pady=40)

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
        self._btn_export_selected.grid(row=0, column=2, sticky="e", padx=(0, 8))

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
        self._btn_export_all.grid(row=0, column=3, sticky="e", padx=0)

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

    def _enqueue_single_file_item(self, path: Path) -> Optional[QueueItem]:
        """Validate and construct a QueueItem, add to tracking and worker queue without updating UI counts."""
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return None

        item_id = str(path)

        # Avoid re-queueing currently queued or processing document
        if item_id in self._queue_items and self._queue_items[item_id].status in (
            QueueItemStatus.QUEUED,
            QueueItemStatus.PROCESSING,
        ):
            return None

        # Compute formatted file size once at creation time (P10)
        try:
            size_bytes = path.stat().st_size
            if size_bytes < 1024:
                file_size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                file_size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                file_size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        except Exception:
            file_size_str = "0 B"

        item = QueueItem(
            item_id=item_id,
            file_path=path,
            status=QueueItemStatus.QUEUED,
            file_size_str=file_size_str,
        )
        self._queue_items[item_id] = item
        self._total_count += 1

        self._create_queue_row_widget(item)
        self._task_queue.put(path)
        return item

    def _batch_insert_queue_items(
        self,
        files: List[Path],
        folder_name: str,
        start_idx: int = 0,
        chunk_size: int = 25,
    ) -> None:
        """Insert queue row widgets in chunks to keep UI responsive during folder drops (P6)."""
        if self._is_shutting_down:
            self._pending_batch_inserts = max(0, self._pending_batch_inserts - 1)
            return

        end_idx = min(len(files), start_idx + chunk_size)
        chunk = files[start_idx:end_idx]

        for p in chunk:
            self._enqueue_single_file_item(p)

        if end_idx < len(files):
            self.after(1, self._batch_insert_queue_items, files, folder_name, end_idx, chunk_size)
        else:
            self._pending_batch_inserts = max(0, self._pending_batch_inserts - 1)
            if self._empty_queue_label.winfo_manager() == "pack":
                self._empty_queue_label.pack_forget()
            self._update_queue_header()
            self._update_footer(f"Enqueued {len(files)} files from {folder_name}")

    def enqueue_file(self, file_path: Union[str, Path], sync: bool = False) -> Optional[threading.Thread]:
        """Submit a document file or folder to the worker task queue and add it to the UI queue table (P6)."""
        if self._is_shutting_down:
            return None

        path = Path(file_path).expanduser().resolve()

        # If a directory is dropped, recursively discover and enqueue supported documents
        if path.is_dir():
            if sync:
                child_files = sorted(
                    p for p in path.rglob("*")
                    if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
                )
                if not child_files:
                    print(f"[GUI Ingest] No supported document files found in directory: {path.name}")
                    self._update_footer(f"No supported documents in {path.name}")
                    return None
                for child in child_files:
                    self._enqueue_single_file_item(child)
                if self._empty_queue_label.winfo_manager() == "pack":
                    self._empty_queue_label.pack_forget()
                self._update_queue_header()
                self._update_footer(f"Enqueued {len(child_files)} files from {path.name}")
                return None

            # Asynchronous recursive scan off main thread + chunked batch insertion (P6)
            def _scan_worker() -> None:
                try:
                    child_files = sorted(
                        p for p in path.rglob("*")
                        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
                    )
                except Exception as exc:
                    logger.warning("Error scanning directory %s: %s", path, exc)
                    child_files = []

                if not child_files:
                    print(f"[GUI Ingest] No supported document files found in directory: {path.name}")
                    self._safe_after(0, lambda: self._update_footer(f"No supported documents in {path.name}"))
                    return

                self._pending_batch_inserts += 1
                self._safe_after(0, self._batch_insert_queue_items, child_files, path.name, 0, 25)

            t = threading.Thread(target=_scan_worker, name=f"FolderScan-{path.name}", daemon=True)
            self._ingest_threads.append(t)
            t.start()
            return t

        # Single file
        item = self._enqueue_single_file_item(path)
        if item is not None:
            if self._empty_queue_label.winfo_manager() == "pack":
                self._empty_queue_label.pack_forget()
            self._update_queue_header()
            self._update_footer()
        return None

    def wait_for_ingest(self, timeout: float = 5.0) -> None:
        """Wait for any active background folder scan and pending UI insertion batches."""
        for t in list(self._ingest_threads):
            if t.is_alive():
                t.join(timeout=timeout)
        self._drain_ui_callbacks()

        deadline = time.time() + timeout
        while time.time() < deadline and self._pending_batch_inserts > 0:
            self._drain_ui_callbacks()
            try:
                self.update()
            except Exception:
                pass
            time.sleep(0.01)
        self._drain_ui_callbacks()
        try:
            self.update()
        except Exception:
            pass

    def _format_queue_item_meta(self, item: QueueItem) -> str:
        """Format 2nd line metadata string for queue rows based on file info and processing status.

        DATA AVAILABILITY RULE:
        - QUEUED: Format and file size only (e.g. 'PDF · 2.4 MB'). Page count is not
          scanned upfront to prevent redundant pre-processing overhead.
        - PROCESSING: Format, file size, and processing indicator.
        - SUCCESS/PARTIAL: Includes total page count yielded from pipeline results and duration.
        - FAILED: Indicates failure state.
        """
        ext = item.file_path.suffix.lstrip(".").upper() or "DOC"
        size_str = item.file_size_str
        if size_str is None:
            # Fallback/caching if QueueItem was instantiated without file_size_str
            try:
                size_bytes = item.file_path.stat().st_size
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            except Exception:
                size_str = "0 B"
            item.file_size_str = size_str

        base_meta = f"{ext} · {size_str}"

        if item.status == QueueItemStatus.QUEUED:
            return base_meta
        elif item.status == QueueItemStatus.PROCESSING:
            return f"{base_meta} · Processing..."
        elif item.status == QueueItemStatus.FAILED:
            return f"{base_meta} · Failed"
        elif item.status == QueueItemStatus.CANCELLED:
            if item.result and item.result.pages:
                count = len(item.result.pages)
                page_str = f"{count} page" if count == 1 else f"{count} pages"
                meta = f"{base_meta} · Cancelled ({page_str})"
            else:
                meta = f"{base_meta} · Cancelled"
            current_dpi = getattr(self.settings, "dpi", None)
            if item.processed_dpi is not None and current_dpi is not None and item.processed_dpi != current_dpi:
                meta += f" · ⚠ processed @{item.processed_dpi} DPI"
            return meta
        else:  # SUCCESS / PARTIAL
            if item.result and item.result.pages:
                count = len(item.result.pages)
                page_str = f"{count} page" if count == 1 else f"{count} pages"
            else:
                page_str = "1 page"
            duration_str = f"{item.duration:.1f}s"
            meta = f"{base_meta} · {page_str} · {duration_str}"
            current_dpi = getattr(self.settings, "dpi", None)
            if item.processed_dpi is not None and current_dpi is not None and item.processed_dpi != current_dpi:
                meta += f" · ⚠ processed @{item.processed_dpi} DPI"
            return meta

    def _create_queue_row_widget(self, item: QueueItem) -> None:
        """Create an interactive 2-line row widget (~56px height) in the scrollable queue list."""
        row = ctk.CTkFrame(
            self._queue_scroll,
            height=56,
            corner_radius=6,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            cursor="hand2",
        )
        row.pack(fill="x", padx=6, pady=3)
        row.grid_columnconfigure(0, weight=0)  # Left Accent Indicator
        row.grid_columnconfigure(1, weight=0)  # File Type Chip
        row.grid_columnconfigure(2, weight=1)  # Text column (Name + Meta)
        row.grid_columnconfigure(3, weight=0)  # Status Dot Badge

        # Left 3px selection accent indicator (height=1 with sticky='ns' prevents frame expansion)
        indicator = ctk.CTkFrame(
            row,
            width=3,
            height=1,
            fg_color="transparent",
            corner_radius=1,
        )
        indicator.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 4))

        # File-type chip badge (PDF or IMG)
        is_pdf = item.file_path.suffix.lower() == ".pdf"
        chip_text = "PDF" if is_pdf else "IMG"
        chip_fg = COLOR_CHIP_PDF_BG if is_pdf else COLOR_CHIP_IMG_BG
        chip_text_col = COLOR_CHIP_PDF_TEXT if is_pdf else COLOR_CHIP_IMG_TEXT

        chip = ctk.CTkLabel(
            row,
            text=chip_text,
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            fg_color=chip_fg,
            text_color=chip_text_col,
            corner_radius=4,
            width=32,
            height=18,
        )
        chip.grid(row=0, column=1, rowspan=2, sticky="w", padx=(2, 6), pady=6)

        # Line 1: Filename
        name = ctk.CTkLabel(
            row,
            text=item.file_path.name,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            height=18,
            anchor="w",
        )
        name.grid(row=0, column=2, sticky="w", padx=(0, 4), pady=(6, 0))

        # Line 2: Format · Size · [Pages] · [Duration/Status]
        detail = ctk.CTkLabel(
            row,
            text=self._format_queue_item_meta(item),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            height=16,
            anchor="w",
        )
        detail.grid(row=1, column=2, sticky="w", padx=(0, 4), pady=(0, 6))

        # Status dot indicator on right
        badge = ctk.CTkLabel(
            row,
            text="●",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_STATUS_QUEUED,
            width=24,
            height=18,
        )
        badge.grid(row=0, column=3, rowspan=2, sticky="e", padx=(4, 10))

        item.row_frame = row
        item.indicator_bar = indicator
        item.chip_label = chip
        item.badge_label = badge
        item.name_label = name
        item.detail_label = detail

        # Clicking any part of the row selects it
        for w in (row, indicator, chip, badge, name, detail):
            w.bind("<Button-1>", lambda e, i_id=item.item_id: self._select_queue_item(i_id))

        # Hover feedback: lighten row bg on mouse enter (respect selected state)
        for w in (row, indicator, chip, badge, name, detail):
            w.bind("<Enter>", lambda e, i_id=item.item_id: self._on_queue_row_enter(e, i_id))
            w.bind("<Leave>", lambda e, i_id=item.item_id: self._on_queue_row_leave(e, i_id))

        # Auto-select the first item if nothing is selected
        if self._selected_item_id is None:
            self._select_queue_item(item.item_id)

    def _select_queue_item(self, item_id: str) -> None:
        """Select a queue item and populate the preview pane with its state or results."""
        if item_id not in self._queue_items:
            return

        # Unhighlight previous row
        if self._selected_item_id and self._selected_item_id in self._queue_items:
            prev_item = self._queue_items[self._selected_item_id]
            if prev_item.row_frame:
                prev_item.row_frame.configure(fg_color=COLOR_INTERACTIVE_NEUTRAL)
            if prev_item.indicator_bar:
                prev_item.indicator_bar.configure(fg_color="transparent")

        if self._selected_item_id != item_id:
            self._current_image_page_idx = 0

        self._selected_item_id = item_id
        item = self._queue_items[item_id]

        # Highlight newly selected row with 1px accent indicator
        if item.row_frame:
            item.row_frame.configure(fg_color=COLOR_ROW_SELECTED_BG)
        if item.indicator_bar:
            item.indicator_bar.configure(fg_color=COLOR_ACCENT_PRIMARY)

        # Render preview content for this item
        self._render_preview(item)

    def _on_tab_changed(self) -> None:
        """Render the newly active tab on-demand for the currently selected item."""
        if self._selected_item_id and self._selected_item_id in self._queue_items:
            self._render_preview(self._queue_items[self._selected_item_id])

    def select_tab(self, tab_name: str) -> None:
        """Select a preview tab programmatically and trigger on-demand rendering."""
        self._tabview.set(tab_name)
        self._on_tab_changed()

    def _render_preview(self, item: QueueItem, tab_name: Optional[str] = None) -> None:
        """Populate the active preview tab based on the queue item's status and results (P1 Lazy Tab Rendering)."""
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
                    md_text = f"[{item.file_path.name} is currently being processed by GLM-OCR vision engine...]"
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
            assert item.result is not None
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
            self._apply_markdown_tags()
        except Exception as exc:
            # Graceful degradation fallback: clear tags and retain plain text
            logger.warning("Markdown tag rendering error, falling back to plain text: %s", exc)
            self._clear_preview_tags()

    def _clear_preview_tags(self) -> None:
        """Remove all formatting tags from the preview text widget."""
        tw = self._tb_preview._textbox
        for tag in (
            "h1", "h2", "h3", "bold", "italic", "code_inline",
            "code_block", "table_header", "table_row", "bullet",
            "divider", "muted",
        ):
            tw.tag_remove(tag, "1.0", "end")

    def _apply_markdown_tags(self) -> None:
        """Parse text in _tb_preview and apply typography tags."""
        tw = self._tb_preview._textbox
        self._clear_preview_tags()

        end_index = tw.index("end-1c")
        if not end_index or "." not in end_index:
            return
        total_lines = int(end_index.split(".")[0])
        in_code_block = False

        for line_no in range(1, total_lines + 1):
            start_idx = f"{line_no}.0"
            end_idx = f"{line_no}.end"
            line = tw.get(start_idx, end_idx)
            stripped = line.strip()

            # Fenced code block check
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                tw.tag_add("muted", start_idx, end_idx)
                continue

            if in_code_block:
                tw.tag_add("code_block", start_idx, end_idx)
                continue

            if not stripped:
                continue

            # Headings
            if stripped.startswith("# "):
                tw.tag_add("h1", start_idx, end_idx)
                continue
            elif stripped.startswith("## "):
                tw.tag_add("h2", start_idx, end_idx)
                continue
            elif stripped.startswith("### "):
                tw.tag_add("h3", start_idx, end_idx)
                continue

            # Horizontal dividers
            if stripped in ("---", "***", "___") or re.match(r"^[-*_]{3,}$", stripped):
                tw.tag_add("divider", start_idx, end_idx)
                continue

            # Table rows
            if stripped.startswith("|") and stripped.endswith("|"):
                if re.match(r"^\|[\s\-:|]+\|$", stripped):
                    tw.tag_add("muted", start_idx, end_idx)
                else:
                    prev_line = tw.get(f"{line_no-1}.0", f"{line_no-1}.end").strip() if line_no > 1 else ""
                    if not (prev_line.startswith("|") and prev_line.endswith("|")):
                        tw.tag_add("table_header", start_idx, end_idx)
                    else:
                        tw.tag_add("table_row", start_idx, end_idx)
                continue

            # Unordered & ordered list bullets
            if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped):
                tw.tag_add("bullet", start_idx, end_idx)

            # Blockquotes
            if stripped.startswith(">"):
                tw.tag_add("italic", start_idx, end_idx)
                continue

            # Inline code: `code`
            for m in re.finditer(r"`([^`]+)`", line):
                tw.tag_add("code_inline", f"{line_no}.{m.start()}", f"{line_no}.{m.end()}")

            # Bold: **bold** or __bold__
            for m in re.finditer(r"(\*\*|__)(.*?)\1", line):
                tw.tag_add("bold", f"{line_no}.{m.start()}", f"{line_no}.{m.end()}")

            # Italic: *text*
            for m in re.finditer(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", line):
                tw.tag_add("italic", f"{line_no}.{m.start()}", f"{line_no}.{m.end()}")

    def _load_image_page_on_demand(
        self,
        file_path: Path,
        page_index: int,
        effective_dpi: Optional[int] = None,
    ) -> Tuple[Optional[Image.Image], Optional[str]]:
        """Load and rasterize a single page on-demand from disk without holding base64 strings in memory (P2).

        If the source file no longer exists (moved or deleted after enqueue), returns a clean
        descriptive error message without raising exceptions.
        """
        if not file_path.is_file():
            return None, f"Source file unavailable:\n{file_path.name}\n\n(File was moved or deleted after enqueue)"

        suffix = file_path.suffix.lower()
        if effective_dpi is None:
            effective_dpi = getattr(self.settings, "dpi", 100) or 100
        scale = effective_dpi / 72.0

        if suffix == ".pdf":
            try:
                with _PDFIUM_LOCK:
                    doc = pdfium.PdfDocument(str(file_path))
                    try:
                        n_pages = len(doc)
                        if n_pages == 0:
                            return None, f"PDF contains 0 pages: {file_path.name}"
                        idx = max(0, min(page_index, n_pages - 1))
                        page = doc[idx]
                        try:
                            pil_img = page.render(scale=scale).to_pil()
                            return pil_img, None
                        finally:
                            page.close()
                    finally:
                        doc.close()
            except pdfium.PdfiumError:
                # Mislabeled extension fallback (e.g. JPEG renamed to .pdf)
                try:
                    with Image.open(file_path) as img:
                        n_frames = getattr(img, "n_frames", 1)
                        idx = max(0, min(page_index, n_frames - 1))
                        img.seek(idx)
                        return img.convert("RGB"), None
                except Exception as fallback_exc:
                    return None, f"Failed to rasterize PDF page: {fallback_exc}"
            except Exception as exc:
                return None, f"Failed to rasterize PDF page: {exc}"

        # Standalone images (PNG, JPG, TIFF, etc.)
        try:
            with Image.open(file_path) as img:
                n_frames = getattr(img, "n_frames", 1)
                idx = max(0, min(page_index, n_frames - 1))
                img.seek(idx)
                return img.convert("RGB"), None
        except Exception as exc:
            # Fallback if image extension was actually a mislabeled PDF
            try:
                with _PDFIUM_LOCK:
                    doc = pdfium.PdfDocument(str(file_path))
                    try:
                        n_pages = len(doc)
                        if n_pages > 0:
                            idx = max(0, min(page_index, n_pages - 1))
                            page = doc[idx]
                            try:
                                return page.render(scale=scale).to_pil(), None
                            finally:
                                page.close()
                    finally:
                        doc.close()
            except Exception:
                pass
            return None, f"Failed to load image: {exc}"

    def _render_image_preview(self, item: QueueItem) -> None:
        """Render original raster scan image for the active document page on-demand (P2)."""
        if not (item.result and item.result.pages):
            self._reset_image_preview()
            return

        total_img_pages = len(item.result.pages)
        if total_img_pages == 0:
            self._reset_image_preview()
            return

        self._current_image_page_idx = max(0, min(self._current_image_page_idx, total_img_pages - 1))
        target_page = item.result.pages[self._current_image_page_idx]

        dpi_val = getattr(item, "processed_dpi", None) or getattr(self.settings, "dpi", 100) or 100
        pil_img, err_msg = self._load_image_page_on_demand(
            item.file_path,
            page_index=self._current_image_page_idx,
            effective_dpi=dpi_val,
        )

        if err_msg or pil_img is None:
            self._current_ctk_image = None
            self._img_display_label.configure(
                image="",
                text=err_msg or "Failed to load image preview",
            )
            self._lbl_img_page.configure(text=f"Page {self._current_image_page_idx + 1} of {total_img_pages}")
            self._lbl_img_info.configure(text="")
            self._btn_img_prev.configure(state="normal" if self._current_image_page_idx > 0 else "disabled")
            self._btn_img_next.configure(state="normal" if self._current_image_page_idx < total_img_pages - 1 else "disabled")
            return

        try:
            if pil_img.mode not in ("RGB", "RGBA"):
                pil_img = pil_img.convert("RGB")

            orig_w, orig_h = pil_img.size
            max_w, max_h = 620, 750
            scale = min(max_w / orig_w, max_h / orig_h, 1.0)
            disp_w = max(1, int(orig_w * scale))
            disp_h = max(1, int(orig_h * scale))

            scaled_img = pil_img.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=scaled_img, dark_image=scaled_img, size=(disp_w, disp_h))
            self._current_ctk_image = ctk_img

            self._img_display_label.configure(image=ctk_img, text="")
            self._lbl_img_page.configure(text=f"Page {self._current_image_page_idx + 1} of {total_img_pages}")
            self._lbl_img_info.configure(text=f"{orig_w} × {orig_h} px @ {dpi_val} DPI")
            self._btn_img_prev.configure(state="normal" if self._current_image_page_idx > 0 else "disabled")
            self._btn_img_next.configure(state="normal" if self._current_image_page_idx < total_img_pages - 1 else "disabled")
        except Exception as exc:
            self._current_ctk_image = None
            self._img_display_label.configure(
                image="",
                text=f"Failed to display image raster: {exc}",
            )
            self._lbl_img_page.configure(text="Page Error")
            self._lbl_img_info.configure(text="")
            self._btn_img_prev.configure(state="disabled")
            self._btn_img_next.configure(state="disabled")

    def _reset_image_preview(self) -> None:
        """Reset the image preview controls and canvas to empty state."""
        self._current_image_page_idx = 0
        self._current_ctk_image = None
        self._img_display_label.configure(
            image="",
            text="No image preview available for this document.\nProcess a document to inspect scan raster.",
        )
        self._lbl_img_page.configure(text="Page 0 of 0")
        self._lbl_img_info.configure(text="")
        self._btn_img_prev.configure(state="disabled")
        self._btn_img_next.configure(state="disabled")

    def _on_img_prev(self) -> None:
        """Navigate to the previous page in Image Preview."""
        if self._current_image_page_idx > 0:
            self._current_image_page_idx -= 1
            if self._selected_item_id and self._selected_item_id in self._queue_items:
                self._render_image_preview(self._queue_items[self._selected_item_id])

    def _on_img_next(self) -> None:
        """Navigate to the next page in Image Preview."""
        if self._selected_item_id and self._selected_item_id in self._queue_items:
            item = self._queue_items[self._selected_item_id]
            total_pages = len(item.result.pages) if item.result and item.result.pages else 0
            if self._current_image_page_idx < total_pages - 1:
                self._current_image_page_idx += 1
                self._render_image_preview(item)

    def _set_textbox_content(self, textbox: ctk.CTkTextbox, content: str) -> None:
        """Safely update text in a read-only CTkTextbox."""
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", content)
        textbox.configure(state="disabled")

    def _update_action_buttons(self) -> None:
        """Update state of Action Bar buttons based on selected and available items."""
        has_selected = (
            self._selected_item_id is not None
            and self._selected_item_id in self._queue_items
        )
        selected_item = self._queue_items[self._selected_item_id] if has_selected else None
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

        # Export Selected: swap colors to preserve muted identity when disabled
        if selected_completed:
            self._btn_export_selected.configure(
                state="normal",
                fg_color=COLOR_ACCENT_PRIMARY,
                text_color="#ffffff",
                border_width=0,
            )
        else:
            self._btn_export_selected.configure(
                state="disabled",
                fg_color=COLOR_INTERACTIVE_NEUTRAL,
                text_color=COLOR_TEXT_SUBTLE,
                border_width=1,
                border_color=COLOR_SURFACE_BORDER,
            )

        if self._is_exporting:
            self._btn_export_all.configure(text="Exporting...", state="disabled")
        else:
            self._btn_export_all.configure(
                text="Export All",
                state="normal" if completed_count > 0 else "disabled"
            )

    def _update_queue_header(self) -> None:
        """Update the queue header label with active total count and cleanup hint (P7)."""
        count = len(self._queue_items)
        self._queue_title.configure(text=f"Queue ({count})")

        finished_count = sum(
            1 for it in self._queue_items.values()
            if it.status in (QueueItemStatus.SUCCESS, QueueItemStatus.FAILED, QueueItemStatus.CANCELLED)
        )
        if finished_count > 100:
            self._queue_cleanup_hint.configure(
                text=f"💡 {finished_count} finished items — consider 'Clear Finished' to keep queue responsive"
            )
            self._queue_cleanup_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        else:
            self._queue_cleanup_hint.grid_forget()

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

    def _on_cancel_current(self) -> None:
        """Signal the current in-flight job to cancel after the current page finishes."""
        if self._current_cancel_event and not self._current_cancel_event.is_set():
            self._current_cancel_event.set()
            self._btn_cancel.configure(text="Cancelling...", state="disabled")
            self._update_footer("Cancelling after current page...")

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

    def _on_export_selected(self) -> None:
        """Export artifacts for the currently selected document."""
        if not self._selected_item_id or self._selected_item_id not in self._queue_items:
            return

        item = self._queue_items[self._selected_item_id]
        if not item.result:
            return

        out_dir = filedialog.askdirectory(title="Select Output Directory for Document")
        if not out_dir:
            return

        out_path = Path(out_dir)
        try:
            unique_stem = resolve_unique_stem(item.file_path.stem, output_dir=out_path, used_stems=set())
            config = JobConfig(output_format=OutputFormat.BOTH)
            saved = save_artifacts(item.result, config=config, output_dir=out_path, base_name=unique_stem)
            self._update_footer(f"Exported {len(saved)} files to {out_path.name}")
            self._btn_export_selected.configure(text="Exported!")
            self.after(1200, lambda: self._btn_export_selected.configure(text="Export Selected"))
        except Exception as exc:
            logger.warning("Failed to export selected document: %s", exc)
            self._update_footer(f"Export error: {_friendly_err(exc)}")

    def _on_export_all(self, sync: bool = False) -> Optional[threading.Thread]:
        """Export artifacts for all successfully processed documents in the queue (P8)."""
        if self._is_exporting:
            return None

        completed_items = [
            it
            for it in self._queue_items.values()
            if it.status == QueueItemStatus.SUCCESS and it.result is not None
        ]
        if not completed_items:
            return None

        out_dir = filedialog.askdirectory(title="Select Output Directory for All Results")
        if not out_dir:
            return None

        out_path = Path(out_dir)
        self._is_exporting = True
        self._btn_export_all.configure(text="Exporting...", state="disabled")
        self._update_footer(f"Exporting 0/{len(completed_items)} documents...")

        def _do_export() -> None:
            total_saved = 0
            used_stems: Set[str] = set()
            config = JobConfig(output_format=OutputFormat.BOTH)
            total_docs = len(completed_items)
            try:
                for idx, it in enumerate(completed_items, start=1):
                    if self._is_shutting_down or self._shutdown_event.is_set():
                        return
                    assert it.result is not None
                    unique_stem = resolve_unique_stem(it.file_path.stem, output_dir=out_path, used_stems=used_stems)
                    saved = save_artifacts(it.result, config=config, output_dir=out_path, base_name=unique_stem)
                    total_saved += len(saved)
                    self._safe_after(
                        0,
                        lambda i=idx, n=total_docs: self._update_footer(f"Exporting {i}/{n} documents..."),
                    )

                def _on_success() -> None:
                    self._update_footer(f"Exported {total_docs} documents ({total_saved} files) to {out_path.name}")
                    self._btn_export_all.configure(text="Exported All!")
                    self.after(1200, self._reset_export_all_button)

                self._safe_after(0, _on_success)
            except Exception as exc:
                logger.warning("Export All error: %s", exc)
                self._safe_after(0, lambda e=exc: self._update_footer(f"Export All error: {_friendly_err(e)}"))
                self._safe_after(0, self._reset_export_all_button)
            finally:
                self._is_exporting = False

        if sync:
            _do_export()
            return None

        thread = threading.Thread(target=_do_export, name="ExportAllWorker", daemon=True)
        self._export_thread = thread
        thread.start()
        return thread

    def _reset_export_all_button(self) -> None:
        """Reset the Export All button text and enabled state after export completes."""
        if self._is_shutting_down:
            return
        completed_count = sum(
            1 for it in self._queue_items.values()
            if it.status == QueueItemStatus.SUCCESS and it.result is not None
        )
        self._btn_export_all.configure(
            text="Export All",
            state="normal" if completed_count > 0 else "disabled",
        )

    def wait_for_export(self, timeout: float = 3.0) -> None:
        """Wait for any active background export thread to complete and drain main loop callbacks."""
        if self._export_thread and self._export_thread.is_alive():
            self._export_thread.join(timeout=timeout)
        self._drain_ui_callbacks()
        try:
            self.update()
        except Exception:
            pass

    def _on_clear_finished(self) -> None:
        """Remove completed and failed items from the queue, keeping pending/active ones."""
        finished_ids = [
            i_id
            for i_id, it in self._queue_items.items()
            if it.status in (QueueItemStatus.SUCCESS, QueueItemStatus.FAILED, QueueItemStatus.CANCELLED)
        ]
        if not finished_ids:
            return

        for i_id in finished_ids:
            item = self._queue_items.pop(i_id)
            if item.row_frame:
                item.row_frame.destroy()

        # If active selection was cleared, reset to first remaining item or initial state
        if self._selected_item_id in finished_ids:
            self._selected_item_id = None
            if self._queue_items:
                first_key = next(iter(self._queue_items))
                self._select_queue_item(first_key)
            else:
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

        self._update_queue_header()
        self._update_action_buttons()

    def _on_browse_files(self) -> None:
        """Open native Windows file picker dialog and enqueue selected files."""
        file_types = [
            ("Supported Documents", "*.pdf;*.png;*.jpg;*.jpeg;*.tiff;*.tif;*.bmp;*.webp"),
            ("PDF Documents", "*.pdf"),
            ("Images", "*.png;*.jpg;*.jpeg;*.tiff;*.tif;*.bmp;*.webp"),
            ("All Files", "*.*"),
        ]
        selected_paths = filedialog.askopenfilenames(
            title="Select Documents for GLM-OCR",
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

    def _on_queue_row_enter(self, event: Any = None, item_id: str = "") -> None:
        """Lighten row background on mouse enter, unless already selected."""
        i_id = item_id or getattr(event, "item_id", "")
        if not i_id and hasattr(event, "widget"):
            for q_id, q_item in self._queue_items.items():
                if event.widget in (
                    q_item.row_frame,
                    q_item.indicator_bar,
                    q_item.chip_label,
                    q_item.badge_label,
                    q_item.name_label,
                    q_item.detail_label,
                ):
                    i_id = q_id
                    break
        if i_id and i_id != self._selected_item_id:
            it = self._queue_items.get(i_id)
            if it and it.row_frame:
                it.row_frame.configure(fg_color=COLOR_INTERACTIVE_HOVER)

    def _on_queue_row_leave(self, event: Any = None, item_id: str = "") -> None:
        """Restore row background on mouse leave, unless already selected."""
        i_id = item_id or getattr(event, "item_id", "")
        if not i_id and hasattr(event, "widget"):
            for q_id, q_item in self._queue_items.items():
                if event.widget in (
                    q_item.row_frame,
                    q_item.indicator_bar,
                    q_item.chip_label,
                    q_item.badge_label,
                    q_item.name_label,
                    q_item.detail_label,
                ):
                    i_id = q_id
                    break
        if i_id and i_id != self._selected_item_id:
            it = self._queue_items.get(i_id)
            if it and it.row_frame:
                it.row_frame.configure(fg_color=COLOR_INTERACTIVE_NEUTRAL)

    # ==========================================================================
    # Background Worker & Event Handlers
    # ==========================================================================

    def _worker_loop(self) -> None:
        """Dedicated background worker loop processing OCR jobs from the task queue."""
        try:
            while not self._shutdown_event.is_set():
                try:
                    item = self._task_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if item is None or self._shutdown_event.is_set():
                    self._task_queue.task_done()
                    break

                file_path_str = str(item)

                # Setup cancel token for this document
                cancel_event = threading.Event()
                self._current_cancel_event = cancel_event

                def _on_engine_page_progress(cur_page: int, tot_pages: int, p_res: PageResult) -> None:
                    self._result_queue.put(
                        WorkerEvent(
                            event_type=WorkerEventType.PAGE_PROGRESS,
                            file_path=file_path_str,
                            current_page=cur_page,
                            total_pages=tot_pages,
                            page_result=p_res,
                        )
                    )

                try:
                    # Apply any pending settings updates at document boundary (SEC-3.1)
                    self._apply_pending_engine_settings()
                    effective_settings = (
                        self.engine.settings
                        if hasattr(self.engine, "settings") and isinstance(self.engine.settings, Settings)
                        else self.settings
                    )
                    job_cfg = JobConfig(
                        max_pages=effective_settings.max_pages,
                        dpi=effective_settings.dpi,
                        max_image_dimension=effective_settings.max_image_dimension,
                    )

                    # Pre-flight startup self-test before processing first document in session
                    if hasattr(self.engine, "verify_backend"):
                        self.engine.verify_backend()

                    # Post STARTED event with effective job dpi
                    self._result_queue.put(
                        WorkerEvent(
                            event_type=WorkerEventType.STARTED,
                            file_path=file_path_str,
                            processed_dpi=job_cfg.dpi,
                        )
                    )

                    result = self.engine.process_document(
                        file_path_str,
                        config=job_cfg,
                        cancel_token=cancel_event,
                        progress_callback=_on_engine_page_progress,
                    )
                    if result.status == JobStatus.CANCELLED or result.cancelled:
                        event_type = WorkerEventType.CANCELLED
                    elif result.status in (JobStatus.SUCCESS, JobStatus.PARTIAL):
                        event_type = WorkerEventType.COMPLETED
                    else:
                        event_type = WorkerEventType.FAILED

                    self._result_queue.put(
                        WorkerEvent(
                            event_type=event_type,
                            file_path=file_path_str,
                            result=result,
                            error=result.error,
                        )
                    )
                except Exception as exc:
                    if not self._shutdown_event.is_set():
                        sys.stderr.write(f"Unexpected error processing {file_path_str}: {exc}\n")
                        traceback.print_exc(file=sys.stderr)
                    self._result_queue.put(
                        WorkerEvent(
                            event_type=WorkerEventType.FAILED,
                            file_path=file_path_str,
                            error=str(exc),
                        )
                    )
                finally:
                    self._current_cancel_event = None
                    self._task_queue.task_done()

        except Exception as crash_exc:
            sys.stderr.write(f"FATAL: OCRWorkerThread crashed: {crash_exc}\n")
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            try:
                self._result_queue.put(
                    WorkerEvent(
                        event_type=WorkerEventType.WORKER_CRASHED,
                        file_path="",
                        error=f"Worker loop crashed: {crash_exc}",
                    )
                )
            except Exception:
                pass

    def _process_result_queue(self) -> None:
        """Periodic timer callback running on the main thread to drain worker events (P5)."""
        self._drain_ui_callbacks()
        while True:
            try:
                event = self._result_queue.get_nowait()
            except queue.Empty:
                break

            self._handle_worker_event(event)

        if not self._is_shutting_down:
            is_active = (not self._task_queue.empty()) or (self._current_cancel_event is not None)
            poll_interval_ms = 50 if is_active else 250
            self._poll_id = self.after(poll_interval_ms, self._process_result_queue)

    _poll_result_queue = _process_result_queue

    def _stop_indeterminate_progress(self) -> None:
        """Stop indeterminate progress bar animation and switch back to determinate mode (F7)."""
        if getattr(self, "_progress_indeterminate", False):
            try:
                self._progress_bar.stop()
                self._progress_bar.configure(mode="determinate")
            except Exception:
                pass
            self._progress_indeterminate = False

    def _handle_worker_event(self, event: WorkerEvent) -> None:
        """Process a single worker event on the main thread and update state/UI."""
        item = self._queue_items.get(event.file_path)

        if event.event_type == WorkerEventType.STARTED:
            print(f"[GUI Worker] Started processing: {event.file_path}")
            try:
                self._progress_bar.configure(mode="indeterminate")
                self._progress_bar.start()
                self._progress_indeterminate = True
            except Exception:
                self._progress_bar.set(0.0)
            self._lbl_page_counter.configure(text="0 / ...")
            self._lbl_progress_info.configure(text=f"Processing {Path(event.file_path).name}...")
            if item:
                item.status = QueueItemStatus.PROCESSING
                if event.processed_dpi is not None:
                    item.processed_dpi = event.processed_dpi
                if item.badge_label:
                    item.badge_label.configure(text="●", text_color=COLOR_STATUS_PROCESSING)
                if item.detail_label:
                    item.detail_label.configure(
                        text=self._format_queue_item_meta(item),
                        text_color=COLOR_STATUS_PROCESSING,
                    )
            self._update_footer(f"Processing: {Path(event.file_path).name}")

        elif event.event_type == WorkerEventType.PAGE_PROGRESS:
            self._stop_indeterminate_progress()
            cur = event.current_page
            tot = max(1, event.total_pages)
            fraction = min(1.0, max(0.0, cur / tot))
            self._progress_bar.set(fraction)
            self._lbl_page_counter.configure(text=f"Page {cur} of {tot}")
            self._lbl_progress_info.configure(text=f"Processing {Path(event.file_path).name} ({int(fraction * 100)}%)")
            self._update_footer(f"Processing: {Path(event.file_path).name} (Page {cur}/{tot})")

            if item:
                item.status = QueueItemStatus.PROCESSING
                if item.result is None:
                    # Accumulator for live per-page preview during processing; overwritten by
                    # the authoritative OCRResult from the COMPLETED event. status=SUCCESS
                    # default is intentionally stale (resolve_status() never called here)
                    # since COMPLETED replaces item.result entirely. (C-3)
                    item.result = OCRResult(file_path=item.file_path, status=JobStatus.SUCCESS)
                if event.page_result:
                    if not any(p.page_num == event.page_result.page_num for p in item.result.pages):
                        item.result.pages.append(event.page_result)

                if self._selected_item_id == item.item_id:
                    self._render_preview(item)
            return

        elif event.event_type == WorkerEventType.COMPLETED:
            self._stop_indeterminate_progress()
            duration = event.result.total_duration if event.result else 0.0
            status_val = event.result.status.value if event.result else "SUCCESS"
            total_pages = len(event.result.pages) if event.result and event.result.pages else 1
            print(f"[GUI Worker] Completed processing: {event.file_path} ({duration:.1f}s)")
            self._success_count += 1
            self._progress_bar.set(1.0)
            self._lbl_page_counter.configure(text=f"{total_pages}/{total_pages} done")
            self._lbl_progress_info.configure(text=f"Completed {Path(event.file_path).name}")
            if item:
                item.status = QueueItemStatus.SUCCESS
                item.result = event.result
                item.duration = duration
                if item.badge_label:
                    badge_color = COLOR_STATUS_SUCCESS if status_val == "SUCCESS" else COLOR_STATUS_PARTIAL
                    item.badge_label.configure(text="●", text_color=badge_color)
                if item.detail_label:
                    item.detail_label.configure(
                        text=self._format_queue_item_meta(item),
                        text_color=COLOR_TEXT_MUTED,
                    )
            self._update_footer(f"Done: {Path(event.file_path).name} ({status_val})")

        elif event.event_type == WorkerEventType.FAILED:
            self._stop_indeterminate_progress()
            err_msg = event.error or "Error"
            print(f"[GUI Worker] Failed processing: {event.file_path} ({err_msg})")
            self._failed_count += 1
            self._progress_bar.set(0.0)
            self._lbl_page_counter.configure(text="Failed")
            self._lbl_progress_info.configure(text=f"Failed: {Path(event.file_path).name}")
            if item:
                item.status = QueueItemStatus.FAILED
                item.result = event.result
                item.error = err_msg
                if item.badge_label:
                    item.badge_label.configure(text="●", text_color=COLOR_STATUS_FAILED)
                if item.detail_label:
                    item.detail_label.configure(
                        text=self._format_queue_item_meta(item),
                        text_color=COLOR_STATUS_FAILED,
                    )
            self._update_footer(f"Failed: {Path(event.file_path).name} - {err_msg}")

        elif event.event_type == WorkerEventType.CANCELLED:
            self._stop_indeterminate_progress()
            err_msg = event.error or "Cancelled"
            print(f"[GUI Worker] Cancelled processing: {event.file_path} ({err_msg})")
            self._progress_bar.set(0.0)
            self._lbl_page_counter.configure(text="Cancelled")
            self._lbl_progress_info.configure(text=f"Cancelled: {Path(event.file_path).name}")
            if item:
                item.status = QueueItemStatus.CANCELLED
                item.result = event.result
                item.error = err_msg
                duration = event.result.total_duration if event.result else 0.0
                item.duration = duration
                if item.badge_label:
                    item.badge_label.configure(text="●", text_color=COLOR_STATUS_CANCELLED)
                if item.detail_label:
                    item.detail_label.configure(
                        text=self._format_queue_item_meta(item),
                        text_color=COLOR_STATUS_CANCELLED,
                    )
            self._update_footer(f"Cancelled: {Path(event.file_path).name}")

        elif event.event_type == WorkerEventType.WORKER_CRASHED:
            self._stop_indeterminate_progress()
            print(f"[GUI Worker] FATAL: Worker thread crashed: {event.error}", file=sys.stderr)
            sys.stderr.flush()
            self._progress_bar.set(0.0)
            self._lbl_page_counter.configure(text="Error")
            self._update_footer(f"Fatal Worker Error: {event.error}")

        # RACE-FREE SELECTION HANDLING:
        # Only refresh the preview pane if the finished item is still the active selection
        if item and self._selected_item_id == item.item_id:
            self._render_preview(item)
        else:
            self._update_action_buttons()

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

    def _start_server_poller(self) -> None:
        """Start background daemon thread periodically querying server health (P5)."""
        try:
            self._apply_server_status_update(self.server_manager.get_status_info())
        except Exception:
            pass

        def _poller_worker() -> None:
            while not self._shutdown_event.is_set():
                poll_interval = 10.0
                try:
                    info = self.server_manager.poll_status()
                    self._safe_after(0, self._apply_server_status_update, info)
                    if info.status == ServerStatus.STARTING:
                        poll_interval = 2.0
                    else:
                        poll_interval = 10.0
                except Exception as exc:
                    logger.debug("Server status poll error: %s", exc)
                    poll_interval = 10.0

                if self._shutdown_event.wait(timeout=poll_interval):
                    break

        thread = threading.Thread(target=_poller_worker, name="ServerPollerThread", daemon=True)
        thread.start()
        self._server_poller_thread = thread

    def _apply_server_status_update(self, info: ServerStatusInfo) -> None:
        """Update header status pill and action button from ServerStatusInfo (P5)."""
        if self._is_shutting_down:
            return

        status = info.status
        ownership = info.ownership

        if self._last_applied_server_status == (status, ownership):
            return
        self._last_applied_server_status = (status, ownership)

        if status != ServerStatus.READY and hasattr(self.engine, "invalidate_backend_verification"):
            self.engine.invalidate_backend_verification()

        if status == ServerStatus.READY:
            ownership_lbl = " (Managed)" if ownership == ServerOwnership.MANAGED else " (Ext)"
            self._server_status_pill.configure(
                text=f"● READY{ownership_lbl}",
                fg_color="#0f3322",
                text_color="#34d399",
            )
            if ownership == ServerOwnership.MANAGED:
                self._btn_server_action.configure(
                    text="Stop Server",
                    state="normal",
                    fg_color="#3d1419",
                    hover_color="#541b22",
                    text_color="#fb7185",
                    border_color="#732531",
                )
            else:
                self._btn_server_action.configure(
                    text="External",
                    state="disabled",
                    fg_color=COLOR_INTERACTIVE_NEUTRAL,
                    text_color=COLOR_TEXT_MUTED,
                    border_color=COLOR_SURFACE_BORDER,
                )

        elif status == ServerStatus.STARTING:
            self._server_status_pill.configure(
                text="● STARTING",
                fg_color="#3d2a00",
                text_color="#fbbf24",
            )
            if ownership == ServerOwnership.MANAGED:
                self._btn_server_action.configure(
                    text="Cancel Launch",
                    state="normal",
                    fg_color="#3d1419",
                    hover_color="#541b22",
                    text_color="#fb7185",
                    border_color="#732531",
                )
            else:
                self._btn_server_action.configure(
                    text="Starting...",
                    state="disabled",
                    fg_color=COLOR_INTERACTIVE_NEUTRAL,
                    text_color=COLOR_TEXT_MUTED,
                    border_color=COLOR_SURFACE_BORDER,
                )

        elif status == ServerStatus.ERROR:
            self._server_status_pill.configure(
                text="● ERROR",
                fg_color="#3d1419",
                text_color="#fb7185",
            )
            self._btn_server_action.configure(
                text="Start Server",
                state="normal",
                fg_color=COLOR_INTERACTIVE_NEUTRAL,
                hover_color=COLOR_INTERACTIVE_HOVER,
                text_color=COLOR_TEXT_PRIMARY,
                border_color=COLOR_SURFACE_BORDER,
            )

        else:  # OFFLINE
            self._server_status_pill.configure(
                text="● OFFLINE",
                fg_color=COLOR_INTERACTIVE_NEUTRAL,
                text_color=COLOR_TEXT_MUTED,
            )
            self._btn_server_action.configure(
                text="Start Server",
                state="normal",
                fg_color=COLOR_INTERACTIVE_NEUTRAL,
                hover_color=COLOR_INTERACTIVE_HOVER,
                text_color=COLOR_TEXT_PRIMARY,
                border_color=COLOR_SURFACE_BORDER,
            )

    def _on_server_action_clicked(self) -> None:
        """Handle user clicks on the server Start/Stop action button."""
        status = self.server_manager.status
        ownership = self.server_manager.ownership

        if (status in (ServerStatus.READY, ServerStatus.STARTING)) and ownership == ServerOwnership.MANAGED:
            self._btn_server_action.configure(text="Stopping...", state="disabled")

            def _stop_worker() -> None:
                try:
                    self.server_manager.stop()
                except Exception as stop_err:
                    logger.warning("Error stopping server: %s", stop_err)
                    self._safe_after(0, lambda: self._update_footer(f"Server stop failed: {_friendly_err(stop_err)}"))
                finally:
                    info = self.server_manager.poll_status()
                    self._safe_after(0, self._apply_server_status_update, info)

            stop_thread = threading.Thread(target=_stop_worker, name="ServerStopWorker", daemon=True)
            self._server_stop_thread = stop_thread
            stop_thread.start()

        elif status in (ServerStatus.OFFLINE, ServerStatus.ERROR):
            self._btn_server_action.configure(text="Starting...", state="disabled")
            self._server_status_pill.configure(
                text="● STARTING",
                fg_color="#3d2a00",
                text_color="#fbbf24",
            )

            def _start_worker() -> None:
                try:
                    self.server_manager.start()
                except Exception as start_err:
                    logger.warning("Error starting server: %s", start_err)
                    self._safe_after(0, lambda: self._update_footer(f"Server start failed: {_friendly_err(start_err)}"))
                finally:
                    info = self.server_manager.poll_status()
                    self._safe_after(0, self._apply_server_status_update, info)

            threading.Thread(target=_start_worker, daemon=True).start()

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

    def _apply_pending_engine_settings(self) -> None:
        """Apply pending settings updates to engine and vision client at safe document boundary."""
        pending_s = getattr(self, "_pending_engine_settings", None)
        if pending_s is not None:
            self._pending_engine_settings = None
            if hasattr(self.engine, "client") and self.engine.client is not None:
                from core.client import resolve_chat_endpoint
                self.engine.client.endpoint = resolve_chat_endpoint(pending_s.local_endpoint)
                self.engine.client.settings = pending_s
            if hasattr(self.engine, "settings"):
                self.engine.settings = pending_s
            self.settings = pending_s

    def _on_settings_saved(self, new_settings: Settings) -> None:
        """Callback invoked when preferences are updated and saved in SettingsWindow."""
        self.settings = new_settings
        self.server_manager.settings = new_settings

        # Queue settings for safe inter-document update (SEC-3.1)
        self._pending_engine_settings = new_settings
        if hasattr(self.engine, "invalidate_backend_verification"):
            self.engine.invalidate_backend_verification()
        if self._current_cancel_event is None:
            self._apply_pending_engine_settings()

        # Refresh queue rows' metadata if DPI setting changed (C-12)
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

        # 1. Cancel active after() polling timer
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

        # 2. Signal worker thread and server poller to stop
        self._shutdown_event.set()

        # 3. Drain unstarted tasks from queue and enqueue termination sentinel
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

        # 4. Join worker thread to exit cleanly
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)

        # 4b. Join export thread if running
        if hasattr(self, "_export_thread") and self._export_thread is not None and self._export_thread.is_alive():
            self._export_thread.join(timeout=1.0)

        # 4c. Join ingest threads if running
        if hasattr(self, "_ingest_threads"):
            for t in self._ingest_threads:
                if t.is_alive():
                    t.join(timeout=0.5)

        # 4d. Join runtime download thread if running
        if hasattr(self, "_runtime_download_thread") and self._runtime_download_thread is not None and self._runtime_download_thread.is_alive():
            self._runtime_download_thread.join(timeout=1.0)

        # 5. Join server poller thread
        if hasattr(self, "_server_poller_thread") and self._server_poller_thread is not None:
            if self._server_poller_thread.is_alive():
                self._server_poller_thread.join(timeout=1.0)

        # 6. Stop managed server and close server manager
        try:
            if hasattr(self, "_server_stop_thread") and self._server_stop_thread is not None:
                if self._server_stop_thread.is_alive():
                    self._server_stop_thread.join(timeout=1.0)
            if hasattr(self, "server_manager") and self.server_manager is not None:
                if getattr(self.server_manager, "is_managed", False):
                    logger.info("Stopping managed server process on application exit...")
                    self.server_manager.stop()
                if hasattr(self.server_manager, "close"):
                    self.server_manager.close()
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
    exceptions via sys.excepthook to %LOCALAPPDATA%\\GLM-OCR\\logs\\app.log.
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        app_data = os.environ.get("LOCALAPPDATA")
        base_dir = Path(app_data) if app_data else (Path.home() / "AppData" / "Local")
        log_dir = base_dir / "GLM-OCR" / "logs"
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
    """Run the GLM-OCR Local GUI application."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print("GLM-OCR Local Studio Desktop GUI")
        print("Usage: python -m gui.app")
        return
    _setup_frozen_logging()
    app = OCRApp()
    try:
        app.mainloop()
    finally:
        app._on_closing()


if __name__ == "__main__":
    main()
