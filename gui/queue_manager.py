"""Queue manager controller for AksaraSight GUI.

Manages queue item state, row widgets, list selection, and ingest batches.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import customtkinter as ctk

from core.constants import SUPPORTED_EXTENSIONS
from core.engine import OCRResult
from gui.theme import (
    COLOR_ACCENT_PRIMARY,
    COLOR_CHIP_IMG_BG,
    COLOR_CHIP_IMG_TEXT,
    COLOR_CHIP_PDF_BG,
    COLOR_CHIP_PDF_TEXT,
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_ROW_SELECTED_BG,
    COLOR_STATUS_QUEUED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    FONT_BODY,
    FONT_CAPTION,
    FONT_CHIP,
    FONT_STATUS_DOT,
)

logger = logging.getLogger(__name__)


class QueueItemStatus(str, Enum):
    """Status states for items in the document queue."""
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


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


def _format_file_size(size_bytes: int) -> str:
    """Format byte size into human-readable B, KB, or MB string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


class QueueManager:
    """Manages the document queue, row widget lifecycles, and ingest batches."""

    def __init__(
        self,
        *,
        queue_scroll: ctk.CTkScrollableFrame,
        empty_queue_label: ctk.CTkLabel,
        queue_title: ctk.CTkLabel,
        queue_cleanup_hint: ctk.CTkLabel,
        task_queue: queue.Queue,
        safe_after: Callable[..., Any],
        after: Callable[..., Any],
        update_footer: Callable[..., Any],
        get_current_dpi: Callable[[], Optional[int]],
        is_shutting_down: Callable[[], bool],
        drain_ui_callbacks: Callable[[], None],
        update_ui: Callable[[], None],
        on_selection_changed: Optional[Callable[[Optional[QueueItem], bool], None]] = None,
        on_queue_emptied: Optional[Callable[[], None]] = None,
        on_queue_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        self._queue_scroll = queue_scroll
        self._empty_queue_label = empty_queue_label
        self._queue_title = queue_title
        self._queue_cleanup_hint = queue_cleanup_hint
        self._task_queue = task_queue
        self._safe_after = safe_after
        self._after = after
        self._update_footer = update_footer
        self._get_current_dpi = get_current_dpi
        self._is_shutting_down = is_shutting_down
        self._drain_ui_callbacks = drain_ui_callbacks
        self._update_ui = update_ui
        self._on_selection_changed = on_selection_changed
        self._on_queue_emptied = on_queue_emptied
        self._on_queue_changed = on_queue_changed

        self._items: Dict[str, QueueItem] = {}
        self._selected_item_id: Optional[str] = None
        self._total_count: int = 0
        self._ingest_threads: List[threading.Thread] = []
        self._pending_batch_inserts: int = 0

    @property
    def items(self) -> Dict[str, QueueItem]:
        return self._items

    @property
    def selected_item_id(self) -> Optional[str]:
        return self._selected_item_id

    @selected_item_id.setter
    def selected_item_id(self, value: Optional[str]) -> None:
        self._selected_item_id = value

    @property
    def total_count(self) -> int:
        return self._total_count

    @total_count.setter
    def total_count(self, value: int) -> None:
        self._total_count = value

    @property
    def ingest_threads(self) -> List[threading.Thread]:
        return self._ingest_threads

    @property
    def pending_batch_inserts(self) -> int:
        return self._pending_batch_inserts

    @pending_batch_inserts.setter
    def pending_batch_inserts(self, value: int) -> None:
        self._pending_batch_inserts = value

    def enqueue_single_file_item(self, path: Path) -> Optional[QueueItem]:
        """Validate and construct a QueueItem, add to tracking and worker queue without updating UI counts."""
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return None

        item_id = str(path)

        # Avoid re-queueing currently queued or processing document
        if item_id in self._items and self._items[item_id].status in (
            QueueItemStatus.QUEUED,
            QueueItemStatus.PROCESSING,
        ):
            return None

        # Compute formatted file size once at creation time (P10)
        try:
            file_size_str = _format_file_size(path.stat().st_size)
        except Exception:
            file_size_str = "0 B"

        item = QueueItem(
            item_id=item_id,
            file_path=path,
            status=QueueItemStatus.QUEUED,
            file_size_str=file_size_str,
        )
        self._items[item_id] = item
        self._total_count += 1

        self.create_row_widget(item)
        self._task_queue.put(path)
        return item

    def batch_insert_items(
        self,
        files: List[Path],
        folder_name: str,
        start_idx: int = 0,
        chunk_size: int = 25,
    ) -> None:
        """Insert queue row widgets in chunks to keep UI responsive during folder drops."""
        if self._is_shutting_down():
            self._pending_batch_inserts = max(0, self._pending_batch_inserts - 1)
            return

        end_idx = min(len(files), start_idx + chunk_size)
        chunk = files[start_idx:end_idx]

        for p in chunk:
            self.enqueue_single_file_item(p)

        if end_idx < len(files):
            self._after(1, self.batch_insert_items, files, folder_name, end_idx, chunk_size)
        else:
            self._pending_batch_inserts = max(0, self._pending_batch_inserts - 1)
            if self._empty_queue_label.winfo_manager() == "pack":
                self._empty_queue_label.pack_forget()
            self.update_header()
            self._update_footer(f"Enqueued {len(files)} files from {folder_name}")

    def enqueue_file(self, file_path: Union[str, Path], sync: bool = False) -> Optional[threading.Thread]:
        """Submit a document file or folder to the worker task queue and add it to the UI queue table."""
        if self._is_shutting_down():
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
                    self.enqueue_single_file_item(child)
                if self._empty_queue_label.winfo_manager() == "pack":
                    self._empty_queue_label.pack_forget()
                self.update_header()
                self._update_footer(f"Enqueued {len(child_files)} files from {path.name}")
                return None

            # Asynchronous recursive scan off main thread + chunked batch insertion
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
                self._safe_after(0, self.batch_insert_items, child_files, path.name, 0, 25)

            t = threading.Thread(target=_scan_worker, name=f"FolderScan-{path.name}", daemon=True)
            self._ingest_threads.append(t)
            t.start()
            return t

        # Single file
        item = self.enqueue_single_file_item(path)
        if item is not None:
            if self._empty_queue_label.winfo_manager() == "pack":
                self._empty_queue_label.pack_forget()
            self.update_header()
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
                self._update_ui()
            except Exception:
                pass
            time.sleep(0.01)
        self._drain_ui_callbacks()
        try:
            self._update_ui()
        except Exception:
            pass

    def format_item_meta(self, item: QueueItem) -> str:
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
                size_str = _format_file_size(item.file_path.stat().st_size)
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
            current_dpi = self._get_current_dpi()
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
            if item.result and any(p.truncated for p in item.result.pages):
                meta += " · ⚠ Truncated"
            current_dpi = self._get_current_dpi()
            if item.processed_dpi is not None and current_dpi is not None and item.processed_dpi != current_dpi:
                meta += f" · ⚠ processed @{item.processed_dpi} DPI"
            return meta

    def create_row_widget(self, item: QueueItem) -> None:
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
            font=FONT_CHIP,
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
            font=FONT_BODY,
            text_color=COLOR_TEXT_PRIMARY,
            height=18,
            anchor="w",
        )
        name.grid(row=0, column=2, sticky="w", padx=(0, 4), pady=(6, 0))

        # Line 2: Format · Size · [Pages] · [Duration/Status]
        detail = ctk.CTkLabel(
            row,
            text=self.format_item_meta(item),
            font=FONT_CAPTION,
            text_color=COLOR_TEXT_MUTED,
            height=16,
            anchor="w",
        )
        detail.grid(row=1, column=2, sticky="w", padx=(0, 4), pady=(0, 6))

        # Status dot indicator on right
        badge = ctk.CTkLabel(
            row,
            text="●",
            font=FONT_STATUS_DOT,
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
            w.bind("<Button-1>", lambda e, i_id=item.item_id: self.select_item(i_id))

        # Hover feedback: lighten row bg on mouse enter (respect selected state)
        for w in (row, indicator, chip, badge, name, detail):
            w.bind("<Enter>", lambda e, i_id=item.item_id: self._on_row_enter(e, i_id))
            w.bind("<Leave>", lambda e, i_id=item.item_id: self._on_row_leave(e, i_id))

        # Auto-select the first item if nothing is selected
        if self._selected_item_id is None:
            self.select_item(item.item_id)

    def select_item(self, item_id: str) -> None:
        """Select a queue item and populate the preview pane with its state or results."""
        if item_id not in self._items:
            return

        # Unhighlight previous row
        if self._selected_item_id and self._selected_item_id in self._items:
            prev_item = self._items[self._selected_item_id]
            if prev_item.row_frame:
                prev_item.row_frame.configure(fg_color=COLOR_INTERACTIVE_NEUTRAL)
            if prev_item.indicator_bar:
                prev_item.indicator_bar.configure(fg_color="transparent")

        selection_changed = self._selected_item_id != item_id

        self._selected_item_id = item_id
        item = self._items[item_id]

        # Highlight newly selected row with 1px accent indicator
        if item.row_frame:
            item.row_frame.configure(fg_color=COLOR_ROW_SELECTED_BG)
        if item.indicator_bar:
            item.indicator_bar.configure(fg_color=COLOR_ACCENT_PRIMARY)

        # Notify selection change to trigger preview rendering and tab updates
        if self._on_selection_changed:
            self._on_selection_changed(item, selection_changed)

    def update_header(self) -> None:
        """Update the queue header label with active total count and cleanup hint."""
        count = len(self._items)
        self._queue_title.configure(text=f"Queue ({count})")

        finished_count = sum(
            1 for it in self._items.values()
            if it.status in (QueueItemStatus.SUCCESS, QueueItemStatus.FAILED, QueueItemStatus.CANCELLED)
        )
        if finished_count > 100:
            self._queue_cleanup_hint.configure(
                text=f"💡 {finished_count} finished items — consider 'Clear Finished' to keep queue responsive"
            )
            self._queue_cleanup_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        else:
            self._queue_cleanup_hint.grid_forget()

    def clear_finished(self) -> None:
        """Remove completed and failed items from the queue, keeping pending/active ones."""
        finished_ids = [
            i_id
            for i_id, it in self._items.items()
            if it.status in (QueueItemStatus.SUCCESS, QueueItemStatus.FAILED, QueueItemStatus.CANCELLED)
        ]
        if not finished_ids:
            return

        for i_id in finished_ids:
            item = self._items.pop(i_id)
            if item.row_frame:
                item.row_frame.destroy()

        # If active selection was cleared, reset to first remaining item or initial state
        if self._selected_item_id in finished_ids:
            self._selected_item_id = None
            if self._items:
                first_key = next(iter(self._items))
                self.select_item(first_key)
            else:
                if self._on_queue_emptied:
                    self._on_queue_emptied()

        self.update_header()
        if self._on_queue_changed:
            self._on_queue_changed()

    def _on_row_enter(self, event: Any = None, item_id: str = "") -> None:
        """Lighten row background on mouse enter, unless already selected."""
        i_id = item_id or getattr(event, "item_id", "")
        if not i_id and hasattr(event, "widget"):
            for q_id, q_item in self._items.items():
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
            it = self._items.get(i_id)
            if it and it.row_frame:
                it.row_frame.configure(fg_color=COLOR_INTERACTIVE_HOVER)

    def _on_row_leave(self, event: Any = None, item_id: str = "") -> None:
        """Restore row background on mouse leave, unless already selected."""
        i_id = item_id or getattr(event, "item_id", "")
        if not i_id and hasattr(event, "widget"):
            for q_id, q_item in self._items.items():
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
            it = self._items.get(i_id)
            if it and it.row_frame:
                it.row_frame.configure(fg_color=COLOR_INTERACTIVE_NEUTRAL)
