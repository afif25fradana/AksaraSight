"""GUI Application for OCR-LLM-Local desktop studio."""

from dataclasses import dataclass, field
from enum import Enum
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
from tkinter import filedialog
import traceback
from typing import Any, Dict, List, Optional, Set, Union

import customtkinter as ctk
import tkinterdnd2 as tkdnd
import tkinterdnd2.TkinterDnD as tdnd

from config.settings import Settings
from core.constants import SUPPORTED_EXTENSIONS
from core.engine import OCREngine
from core.formatter import format_output, save_artifacts
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat


class WorkerEventType(str, Enum):
    """Event types posted from the background worker thread to the main UI thread."""
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WORKER_CRASHED = "WORKER_CRASHED"


class QueueItemStatus(str, Enum):
    """Status states for items in the document queue."""
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class WorkerEvent:
    """Structured event emitted by the worker thread across the result queue."""
    event_type: WorkerEventType
    file_path: str
    result: Optional[OCRResult] = None
    error: Optional[str] = None


@dataclass
class QueueItem:
    """State model for a document item tracked in the UI queue manager."""
    item_id: str
    file_path: Path
    status: QueueItemStatus = QueueItemStatus.QUEUED
    duration: float = 0.0
    result: Optional[OCRResult] = None
    error: Optional[str] = None
    # UI references
    row_frame: Optional[ctk.CTkFrame] = None
    indicator_bar: Optional[ctk.CTkFrame] = None
    badge_label: Optional[ctk.CTkLabel] = None
    name_label: Optional[ctk.CTkLabel] = None
    detail_label: Optional[ctk.CTkLabel] = None


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


# Design System Tokens - Warm Carbon & Scanner Amber
COLOR_CANVAS_BG = "#141517"
COLOR_SURFACE_1 = "#1c1e22"
COLOR_SURFACE_2 = "#17181c"
COLOR_SURFACE_BORDER = "#2a2c33"
COLOR_SURFACE_BORDER_HOVER = "#3a3d46"
COLOR_INTERACTIVE_NEUTRAL = "#22242b"
COLOR_INTERACTIVE_HOVER = "#282a33"
COLOR_ROW_SELECTED_BG = "#2a2d36"
COLOR_ACCENT_AMBER = "#d97706"
COLOR_ACCENT_AMBER_HOVER = "#f59e0b"
COLOR_ACCENT_AMBER_DISABLED = "#7c4a0a"
COLOR_ACCENT_AMBER_DISABLED_TEXT = "#a08060"
COLOR_SCROLLBAR_THUMB = "#252830"
COLOR_SCROLLBAR_THUMB_HOVER = "#33363f"
COLOR_TEXT_PRIMARY = "#f3f4f6"
COLOR_TEXT_MUTED = "#9ca3af"
COLOR_TEXT_SUBTLE = "#858d99"
COLOR_STATUS_QUEUED = "#858d99"
COLOR_STATUS_PROCESSING = "#f59e0b"
COLOR_STATUS_SUCCESS = "#10b981"
COLOR_STATUS_PARTIAL = "#fbbf24"
COLOR_STATUS_FAILED = "#f43f5e"
COLOR_DRAGOVER_BG = "#1e2028"


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
    ) -> None:
        """Initialize the GUI application window, layout, and worker thread."""
        super().__init__()
        self.TkdndVersion = _init_tkinterdnd(self)
        try:
            self.tk.call("proc", "bgerror", "msg", "")
        except Exception:
            pass

        self.settings = settings or getattr(engine, "settings", None) or Settings.from_env()
        self.engine = engine or OCREngine(self.settings)

        # Window appearance and geometry
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=COLOR_CANVAS_BG)
        self.title("GLM-OCR Local Studio")
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

        # Build UI layout
        self._build_layout()

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
            text="v0.1",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        version_badge.pack(side="left", padx=(8, 0), pady=(3, 0))

        # Backend indicator badge
        backend_str = f"Backend: {self.settings.backend} ({self.settings.local_endpoint})"
        self._backend_badge = ctk.CTkLabel(
            header_frame,
            text=backend_str,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            text_color=COLOR_TEXT_MUTED,
            corner_radius=6,
            padx=10,
            pady=4,
        )
        self._backend_badge.grid(row=0, column=1, sticky="e", padx=16, pady=8)

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
        right_container.grid_rowconfigure(1, weight=0)  # Action Bar

        # Tabview styled as compact segmented control (~30px height, corner radius 6)
        # Active tab: dark fill + amber text (4.86:1 contrast, WCAG AA verified).
        # Amber reserved for interactive signals, not static navigation background.
        self._tabview = ctk.CTkTabview(
            right_container,
            corner_radius=6,
            fg_color=COLOR_SURFACE_1,
            segmented_button_selected_color=COLOR_INTERACTIVE_NEUTRAL,
            segmented_button_selected_hover_color=COLOR_INTERACTIVE_HOVER,
            segmented_button_fg_color=COLOR_SURFACE_2,
            segmented_button_unselected_color=COLOR_SURFACE_2,
            segmented_button_unselected_hover_color=COLOR_INTERACTIVE_HOVER,
        )
        self._tabview._segmented_button.configure(
            height=30,
            corner_radius=6,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._tabview.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 8))

        tab_markdown = self._tabview.add("Raw Markdown")
        tab_preview = self._tabview.add("Preview")
        tab_json = self._tabview.add("JSON Tree")

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
        self._tb_preview.pack(fill="both", expand=True, padx=4, pady=4)

        # Tab 3: JSON Tree Textbox
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
        self._set_textbox_content(
            self._tb_preview,
            "Document Preview\n\nNo document selected. Drop or select a file to run local OCR.",
        )
        self._set_textbox_content(
            self._tb_json,
            '{\n  "status": "idle",\n  "message": "Select a document from the queue to inspect structured JSON output."\n}',
        )

        # Action Bar with clear primary (amber) and secondary (neutral with border) weights
        action_bar = ctk.CTkFrame(right_container, fg_color="transparent")
        action_bar.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        action_bar.grid_columnconfigure(0, weight=1)
        action_bar.grid_columnconfigure(1, weight=0)
        action_bar.grid_columnconfigure(2, weight=0)

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

        # Primary Button: Warm scanner amber fill (starts disabled with muted tint)
        self._btn_export_selected = ctk.CTkButton(
            action_bar,
            text="Export Selected",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLOR_ACCENT_AMBER_DISABLED,
            hover_color=COLOR_ACCENT_AMBER_HOVER,
            text_color=COLOR_ACCENT_AMBER_DISABLED_TEXT,
            corner_radius=6,
            height=30,
            state="disabled",
            command=self._on_export_selected,
        )
        self._btn_export_selected.grid(row=0, column=1, sticky="e", padx=(0, 8))

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
        self._btn_export_all.grid(row=0, column=2, sticky="e", padx=0)

    def _build_footer(self) -> None:
        """Build the bottom status bar (~30px height, split into status label and counters)."""
        footer_frame = ctk.CTkFrame(self, corner_radius=0, height=30, fg_color=COLOR_SURFACE_1)
        footer_frame.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        footer_frame.grid_columnconfigure(0, weight=1)
        footer_frame.grid_columnconfigure(1, weight=0)

        # Left: Status indicator label
        self._footer_status = ctk.CTkLabel(
            footer_frame,
            text="Ready",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._footer_status.grid(row=0, column=0, sticky="w", padx=16, pady=(4, 5))
        self._status_label = self._footer_status

        # Right: Counters with numbers slightly brighter than the labels
        counters_frame = ctk.CTkFrame(footer_frame, fg_color="transparent")
        counters_frame.grid(row=0, column=1, sticky="e", padx=16, pady=(4, 5))

        lbl_tot = ctk.CTkLabel(
            counters_frame,
            text="Total: ",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        lbl_tot.pack(side="left")

        self._lbl_total_val = ctk.CTkLabel(
            counters_frame,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._lbl_total_val.pack(side="left", padx=(0, 10))

        lbl_succ = ctk.CTkLabel(
            counters_frame,
            text="Success: ",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        lbl_succ.pack(side="left")

        self._lbl_success_val = ctk.CTkLabel(
            counters_frame,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._lbl_success_val.pack(side="left", padx=(0, 10))

        lbl_fail = ctk.CTkLabel(
            counters_frame,
            text="Failed: ",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        lbl_fail.pack(side="left")

        self._lbl_failed_val = ctk.CTkLabel(
            counters_frame,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        self._lbl_failed_val.pack(side="left")

        self._footer_counters = counters_frame

    # ==========================================================================
    # Queue Management & Selection
    # ==========================================================================

    def enqueue_file(self, file_path: Union[str, Path]) -> None:
        """Submit a document file to the worker task queue and add it to the UI queue table."""
        if self._is_shutting_down:
            return

        path = Path(file_path).expanduser().resolve()
        item_id = str(path)

        # Ignore non-existent files or unsupported extensions if dropped
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS and not path.is_dir():
            print(f"[GUI Ingest] Skipped unsupported file: {path.name}")
            return

        # Avoid re-queueing currently queued or processing document
        if item_id in self._queue_items and self._queue_items[item_id].status in (
            QueueItemStatus.QUEUED,
            QueueItemStatus.PROCESSING,
        ):
            return

        # Create queue item model
        item = QueueItem(item_id=item_id, file_path=path, status=QueueItemStatus.QUEUED)
        self._queue_items[item_id] = item
        self._total_count += 1

        # Create row widget
        self._create_queue_row_widget(item)

        # Hide empty queue label
        if self._empty_queue_label.winfo_manager() == "pack":
            self._empty_queue_label.pack_forget()

        # Update UI counts
        self._update_queue_header()
        self._update_footer()

        # Submit to background worker
        self._task_queue.put(path)

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

        base_meta = f"{ext} · {size_str}"

        if item.status == QueueItemStatus.QUEUED:
            return base_meta
        elif item.status == QueueItemStatus.PROCESSING:
            return f"{base_meta} · Processing..."
        elif item.status == QueueItemStatus.FAILED:
            return f"{base_meta} · Failed"
        else:  # SUCCESS / PARTIAL
            if item.result and item.result.pages:
                count = len(item.result.pages)
                page_str = f"{count} page" if count == 1 else f"{count} pages"
            else:
                page_str = "1 page"
            duration_str = f"{item.duration:.1f}s"
            return f"{base_meta} · {page_str} · {duration_str}"

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
        row.grid_columnconfigure(1, weight=1)  # Text column (Name + Meta)
        row.grid_columnconfigure(2, weight=0)  # Status Badge

        # Left 3px selection accent indicator (height=1 with sticky='ns' prevents frame expansion)
        indicator = ctk.CTkFrame(
            row,
            width=3,
            height=1,
            fg_color="transparent",
            corner_radius=1,
        )
        indicator.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 6))

        # Line 1: Filename
        name = ctk.CTkLabel(
            row,
            text=item.file_path.name,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            height=18,
            anchor="w",
        )
        name.grid(row=0, column=1, sticky="w", padx=(0, 4), pady=(6, 0))

        # Line 2: Format · Size · [Pages] · [Duration/Status]
        detail = ctk.CTkLabel(
            row,
            text=self._format_queue_item_meta(item),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
            height=16,
            anchor="w",
        )
        detail.grid(row=1, column=1, sticky="w", padx=(0, 4), pady=(0, 6))

        # Status badge / glyph on right
        badge = ctk.CTkLabel(
            row,
            text="[ ]",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=COLOR_STATUS_QUEUED,
            width=32,
            height=18,
        )
        badge.grid(row=0, column=2, rowspan=2, sticky="e", padx=(4, 10))

        item.row_frame = row
        item.indicator_bar = indicator
        item.badge_label = badge
        item.name_label = name
        item.detail_label = detail

        # Clicking any part of the row selects it
        for w in (row, indicator, badge, name, detail):
            w.bind("<Button-1>", lambda e, i_id=item.item_id: self._select_queue_item(i_id))

        # Hover feedback: lighten row bg on mouse enter (respect selected state)
        for w in (row, indicator, badge, name, detail):
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

        self._selected_item_id = item_id
        item = self._queue_items[item_id]

        # Highlight newly selected row with 1px accent indicator
        if item.row_frame:
            item.row_frame.configure(fg_color=COLOR_ROW_SELECTED_BG)
        if item.indicator_bar:
            item.indicator_bar.configure(fg_color=COLOR_ACCENT_AMBER)

        # Render preview content for this item
        self._render_preview(item)

    def _render_preview(self, item: QueueItem) -> None:
        """Populate the 3-tab preview pane based on the queue item's status and results."""
        if item.status == QueueItemStatus.QUEUED:
            md_text = f"[{item.file_path.name} is queued for processing... waiting for worker thread]"
            prev_text = (
                f"Document Queued: {item.file_path.name}\n\n"
                "This document is waiting in the queue. Processing will begin automatically."
            )
            json_text = json.dumps(
                {"status": "QUEUED", "file": item.file_path.name},
                indent=2,
            )
        elif item.status == QueueItemStatus.PROCESSING:
            md_text = f"[{item.file_path.name} is currently being processed by GLM-OCR vision engine...]"
            prev_text = (
                f"Processing Document: {item.file_path.name}\n\n"
                "Extracting and rasterizing pages, dispatching inference requests to local backend."
            )
            json_text = json.dumps(
                {"status": "PROCESSING", "file": item.file_path.name},
                indent=2,
            )
        elif item.status == QueueItemStatus.FAILED:
            err_msg = item.error or (item.result.error if item.result else "Unknown processing failure")
            md_text = f"Error processing {item.file_path.name}:\n\n{err_msg}"
            prev_text = f"Processing Failed: {item.file_path.name}\n\nError:\n{err_msg}"
            json_text = item.result.to_json() if item.result else json.dumps(
                {"status": "FAILED", "file": item.file_path.name, "error": err_msg},
                indent=2,
            )
        else:  # SUCCESS / PARTIAL
            assert item.result is not None
            md_text = item.result.to_markdown()
            prev_text = item.result.to_markdown()
            json_text = item.result.to_json()

        self._set_textbox_content(self._tb_markdown, md_text)
        self._set_textbox_content(self._tb_preview, prev_text)
        self._set_textbox_content(self._tb_json, json_text)

        self._update_action_buttons()

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
        selected_completed = (
            has_selected
            and self._queue_items[self._selected_item_id].status == QueueItemStatus.SUCCESS
            and self._queue_items[self._selected_item_id].result is not None
        )

        completed_count = sum(
            1
            for it in self._queue_items.values()
            if it.status == QueueItemStatus.SUCCESS and it.result is not None
        )

        self._btn_copy.configure(state="normal" if selected_completed else "disabled")

        # Export Selected: swap colors to preserve muted amber identity when disabled
        if selected_completed:
            self._btn_export_selected.configure(
                state="normal",
                fg_color=COLOR_ACCENT_AMBER,
                text_color="#ffffff",
            )
        else:
            self._btn_export_selected.configure(
                state="disabled",
                fg_color=COLOR_ACCENT_AMBER_DISABLED,
                text_color=COLOR_ACCENT_AMBER_DISABLED_TEXT,
            )

        self._btn_export_all.configure(
            state="normal" if completed_count > 0 else "disabled"
        )

    def _update_queue_header(self) -> None:
        """Update the queue header label with active total count."""
        count = len(self._queue_items)
        self._queue_title.configure(text=f"Queue ({count})")

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

        markdown_text = item.result.to_markdown()
        self.clipboard_clear()
        self.clipboard_append(markdown_text)

        # Temporary visual feedback
        self._btn_copy.configure(text="Copied!")
        self.after(1200, lambda: self._btn_copy.configure(text="Copy to Clipboard"))

    @staticmethod
    def _resolve_unique_stem(base_stem: str, used_stems: Set[str], output_dir: Path) -> str:
        """Resolve a unique file stem within output_dir and the current export batch."""
        stem = base_stem
        counter = 1
        while (
            stem in used_stems
            or (output_dir / f"{stem}.md").exists()
            or (output_dir / f"{stem}.json").exists()
        ):
            counter += 1
            stem = f"{base_stem}_{counter}"
        used_stems.add(stem)
        return stem

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
            base_stem = re.sub(r'[<>:"/\\|?*]', "_", item.file_path.stem) or "ocr_result"
            unique_stem = self._resolve_unique_stem(base_stem, set(), out_path)
            config = JobConfig(output_format=OutputFormat.BOTH)
            saved = save_artifacts(item.result, config=config, output_dir=out_path, base_name=unique_stem)
            self._update_footer(f"Exported {len(saved)} files to {out_path.name}")
            self._btn_export_selected.configure(text="Exported!")
            self.after(1200, lambda: self._btn_export_selected.configure(text="Export Selected"))
        except Exception as exc:
            self._update_footer(f"Export error: {exc}")

    def _on_export_all(self) -> None:
        """Export artifacts for all successfully processed documents in the queue."""
        completed_items = [
            it
            for it in self._queue_items.values()
            if it.status == QueueItemStatus.SUCCESS and it.result is not None
        ]
        if not completed_items:
            return

        out_dir = filedialog.askdirectory(title="Select Output Directory for All Results")
        if not out_dir:
            return

        out_path = Path(out_dir)
        total_saved = 0
        used_stems: Set[str] = set()
        config = JobConfig(output_format=OutputFormat.BOTH)

        try:
            for it in completed_items:
                assert it.result is not None
                base_stem = re.sub(r'[<>:"/\\|?*]', "_", it.file_path.stem) or "ocr_result"
                unique_stem = self._resolve_unique_stem(base_stem, used_stems, out_path)
                saved = save_artifacts(it.result, config=config, output_dir=out_path, base_name=unique_stem)
                total_saved += len(saved)

            self._update_footer(f"Exported {len(completed_items)} documents ({total_saved} files) to {out_path.name}")
            self._btn_export_all.configure(text="Exported All!")
            self.after(1200, lambda: self._btn_export_all.configure(text="Export All"))
        except Exception as exc:
            self._update_footer(f"Export All error: {exc}")

    def _on_clear_finished(self) -> None:
        """Remove completed and failed items from the queue, keeping pending/active ones."""
        finished_ids = [
            i_id
            for i_id, it in self._queue_items.items()
            if it.status in (QueueItemStatus.SUCCESS, QueueItemStatus.FAILED)
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
                self._set_textbox_content(
                    self._tb_preview,
                    "Document Preview\n\nNo document selected. Drop or select a file to run local OCR.",
                )
                self._set_textbox_content(
                    self._tb_json,
                    '{\n  "status": "idle",\n  "message": "Select a document from the queue to inspect structured JSON output."\n}',
                )
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
        """Visual feedback when dragging files over the drop zone (amber border + tinted bg)."""
        self._drop_zone.configure(border_color=COLOR_ACCENT_AMBER, fg_color=COLOR_DRAGOVER_BG)
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

                # Post STARTED event
                self._result_queue.put(
                    WorkerEvent(
                        event_type=WorkerEventType.STARTED,
                        file_path=file_path_str,
                    )
                )

                try:
                    result = self.engine.process_document(file_path_str)
                    if result.status in (JobStatus.SUCCESS, JobStatus.PARTIAL):
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
        """Periodic timer callback running on the main thread to drain worker events."""
        while True:
            try:
                event = self._result_queue.get_nowait()
            except queue.Empty:
                break

            self._handle_worker_event(event)

        if not self._is_shutting_down:
            self._poll_id = self.after(50, self._process_result_queue)

    _poll_result_queue = _process_result_queue

    def _handle_worker_event(self, event: WorkerEvent) -> None:
        """Process a single worker event on the main thread and update state/UI."""
        item = self._queue_items.get(event.file_path)

        if event.event_type == WorkerEventType.STARTED:
            print(f"[GUI Worker] Started processing: {event.file_path}")
            if item:
                item.status = QueueItemStatus.PROCESSING
                if item.badge_label:
                    item.badge_label.configure(text="[>]", text_color=COLOR_STATUS_PROCESSING)
                if item.detail_label:
                    item.detail_label.configure(
                        text=self._format_queue_item_meta(item),
                        text_color=COLOR_STATUS_PROCESSING,
                    )
            self._update_footer(f"Processing: {Path(event.file_path).name}")

        elif event.event_type == WorkerEventType.COMPLETED:
            duration = event.result.total_duration if event.result else 0.0
            status_val = event.result.status.value if event.result else "SUCCESS"
            print(f"[GUI Worker] Completed processing: {event.file_path} ({duration:.1f}s)")
            self._success_count += 1
            if item:
                item.status = QueueItemStatus.SUCCESS
                item.result = event.result
                item.duration = duration
                if item.badge_label:
                    badge_icon = "[✓]" if status_val == "SUCCESS" else "[~]"
                    badge_color = COLOR_STATUS_SUCCESS if status_val == "SUCCESS" else COLOR_STATUS_PARTIAL
                    item.badge_label.configure(text=badge_icon, text_color=badge_color)
                if item.detail_label:
                    item.detail_label.configure(
                        text=self._format_queue_item_meta(item),
                        text_color=COLOR_TEXT_SUBTLE,
                    )
            self._update_footer(f"Done: {Path(event.file_path).name} ({status_val})")

        elif event.event_type == WorkerEventType.FAILED:
            err_msg = event.error or "Error"
            print(f"[GUI Worker] Failed processing: {event.file_path} ({err_msg})")
            self._failed_count += 1
            if item:
                item.status = QueueItemStatus.FAILED
                item.result = event.result
                item.error = err_msg
                if item.badge_label:
                    item.badge_label.configure(text="[✗]", text_color=COLOR_STATUS_FAILED)
                if item.detail_label:
                    item.detail_label.configure(
                        text=self._format_queue_item_meta(item),
                        text_color=COLOR_STATUS_FAILED,
                    )
            self._update_footer(f"Failed: {Path(event.file_path).name} - {err_msg}")

        elif event.event_type == WorkerEventType.WORKER_CRASHED:
            print(f"[GUI Worker] FATAL: Worker thread crashed: {event.error}", file=sys.stderr)
            sys.stderr.flush()
            # TODO (Phase 3 Layout): Surface this to the user visually in the UI / dialog once the queue table exists
            self._update_footer(f"Fatal Worker Error: {event.error}")

        # RACE-FREE SELECTION HANDLING:
        # Only refresh the preview pane if the finished item is still the active selection
        if item and self._selected_item_id == item.item_id:
            self._render_preview(item)
        else:
            self._update_action_buttons()

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

        # 2. Signal worker thread to stop
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

        # 4. Join to allow worker to finish and exit cleanly
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)

        # 5. Explicitly close VisionClient / network sessions
        try:
            if hasattr(self.engine, "close"):
                self.engine.close()
            elif hasattr(self.engine, "client") and hasattr(self.engine.client, "close"):
                self.engine.client.close()
        except Exception as close_exc:
            sys.stderr.write(f"Warning: error closing engine client: {close_exc}\n")

        # 6. Flush pending idle tasks and destroy window
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    """Run the GLM-OCR Local GUI application."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print("GLM-OCR Local Studio Desktop GUI")
        print("Usage: python -m gui.app")
        return
    app = OCRApp()
    app.mainloop()


if __name__ == "__main__":
    main()
