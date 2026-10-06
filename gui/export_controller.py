"""Export controller for AksaraSight Desktop Studio.

Manages single and batch artifact exports, format selection, background export
worker threads, and transient action button text/state transitions.
"""

from __future__ import annotations

import logging
from pathlib import Path
import threading
from tkinter import filedialog
from typing import Any, Callable, List, Optional, Set

from core.formatter import resolve_unique_stem, save_artifacts
from core.models import JobConfig, OutputFormat
from gui.queue_manager import QueueItem, QueueItemStatus
from gui.theme import (
    COLOR_ACCENT_PRIMARY,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_SURFACE_BORDER,
    COLOR_TEXT_SUBTLE,
)

logger = logging.getLogger(__name__)

_FORMAT_EXTENSIONS = {
    OutputFormat.MARKDOWN: (".md",),
    OutputFormat.JSON: (".json",),
    OutputFormat.BOTH: (".md", ".json"),
    OutputFormat.DOCX: (".docx",),
}


class ExportController:
    """Manages document export workflows, format resolution, and export button state."""

    def __init__(
        self,
        queue_manager: Any,
        safe_after: Callable[[int, Any], None],
        after: Callable[[int, Any], Any],
        update_footer: Callable[[Optional[str]], None],
        is_shutting_down: Callable[[], bool],
        shutdown_event: threading.Event,
        drain_ui_callbacks: Callable[[], None],
        update_ui: Optional[Callable[[], None]] = None,
        ask_directory: Optional[Callable[..., Optional[str]]] = None,
        btn_export_selected: Optional[Any] = None,
        btn_export_all: Optional[Any] = None,
        opt_export_format: Optional[Any] = None,
        format_error: Callable[[Any], str] = str,
        on_action_buttons_changed: Optional[Callable[[], None]] = None,
        save_artifacts: Optional[Callable[..., Any]] = None,
        resolve_unique_stem: Optional[Callable[..., str]] = None,
    ) -> None:
        self._queue_manager = queue_manager
        self.safe_after = safe_after
        self.after = after
        self.update_footer = update_footer
        self.is_shutting_down = is_shutting_down
        self.shutdown_event = shutdown_event
        self.drain_ui_callbacks = drain_ui_callbacks
        self.update_ui = update_ui
        self.ask_directory = ask_directory
        self.btn_export_selected = btn_export_selected
        self.btn_export_all = btn_export_all
        self.opt_export_format = opt_export_format
        self.format_error = format_error
        self.on_action_buttons_changed = on_action_buttons_changed
        self.save_artifacts = save_artifacts
        self.resolve_unique_stem = resolve_unique_stem

        self._is_exporting: bool = False
        self._export_thread: Optional[threading.Thread] = None

    @property
    def queue_manager(self) -> Any:
        if callable(self._queue_manager):
            return self._queue_manager()
        return self._queue_manager

    @queue_manager.setter
    def queue_manager(self, value: Any) -> None:
        self._queue_manager = value

    @property
    def is_exporting(self) -> bool:
        return self._is_exporting

    @property
    def export_thread(self) -> Optional[threading.Thread]:
        return self._export_thread

    def get_selected_export_format(self) -> OutputFormat:
        """Return the OutputFormat corresponding to the currently selected export option."""
        if self.opt_export_format is not None and hasattr(self.opt_export_format, "get"):
            val = self.opt_export_format.get()
            if val == "Word Document (.docx)":
                return OutputFormat.DOCX
        return OutputFormat.BOTH

    def update_buttons(self, selected_completed: bool, completed_count: int) -> None:
        """Update export buttons text, enabled state, and colors based on queue state.

        Preserves transient feedback text ('Exported!' and 'Exported All!') during
        worker queue event flushes within the active cooldown period.
        """
        if self.btn_export_selected is not None:
            export_selected_text = (
                "Exported!"
                if self.btn_export_selected.cget("text") == "Exported!"
                else "Export Selected"
            )
            if selected_completed:
                self.btn_export_selected.configure(
                    text=export_selected_text,
                    state="normal",
                    fg_color=COLOR_ACCENT_PRIMARY,
                    text_color="#ffffff",
                    border_width=0,
                )
            else:
                self.btn_export_selected.configure(
                    text=export_selected_text,
                    state="disabled",
                    fg_color=COLOR_INTERACTIVE_NEUTRAL,
                    text_color=COLOR_TEXT_SUBTLE,
                    border_width=1,
                    border_color=COLOR_SURFACE_BORDER,
                )

        if self.btn_export_all is not None:
            if self._is_exporting:
                self.btn_export_all.configure(text="Exporting...", state="disabled")
            else:
                export_all_text = (
                    "Exported All!"
                    if self.btn_export_all.cget("text") == "Exported All!"
                    else "Export All"
                )
                self.btn_export_all.configure(
                    text=export_all_text,
                    state="normal" if completed_count > 0 else "disabled",
                )

    def on_export_selected(self) -> None:
        """Export artifacts for the currently selected document."""
        selected_id = self.queue_manager.selected_item_id if self.queue_manager else None
        if not selected_id or not self.queue_manager or selected_id not in self.queue_manager.items:
            return

        item = self.queue_manager.items[selected_id]
        if not item.result:
            return

        ask_dir = self.ask_directory or filedialog.askdirectory
        out_dir = ask_dir(title="Select Output Directory for Document")
        if not out_dir:
            return

        out_path = Path(out_dir)
        try:
            selected_fmt = self.get_selected_export_format()
            active_exts = _FORMAT_EXTENSIONS.get(selected_fmt, (".md", ".json", ".docx"))
            stem_resolver = self.resolve_unique_stem or resolve_unique_stem
            unique_stem = stem_resolver(
                item.file_path.stem,
                output_dir=out_path,
                used_stems=set(),
                extensions=active_exts,
            )
            config = JobConfig(output_format=selected_fmt)
            do_save = self.save_artifacts or save_artifacts
            saved = do_save(item.result, config=config, output_dir=out_path, base_name=unique_stem)
            self.update_footer(f"Exported {len(saved)} files to {out_path.name}")
            if self.btn_export_selected is not None:
                self.btn_export_selected.configure(text="Exported!")
            self.after(1200, self.reset_export_selected_button)
        except Exception as exc:
            logger.warning("Failed to export selected document: %s", exc)
            self.update_footer(f"Export error: {self.format_error(exc)}")

    def on_export_all(self, sync: bool = False) -> Optional[threading.Thread]:
        """Export artifacts for all successfully processed documents in the queue."""
        if self._is_exporting:
            return None

        if not self.queue_manager:
            return None

        completed_items = [
            it
            for it in self.queue_manager.items.values()
            if it.status == QueueItemStatus.SUCCESS and it.result is not None
        ]
        if not completed_items:
            return None

        ask_dir = self.ask_directory or filedialog.askdirectory
        out_dir = ask_dir(title="Select Output Directory for All Results")
        if not out_dir:
            return None

        out_path = Path(out_dir)
        self._is_exporting = True
        if self.btn_export_all is not None:
            self.btn_export_all.configure(text="Exporting...", state="disabled")
        self.update_footer(f"Exporting 0/{len(completed_items)} documents...")

        config = JobConfig(output_format=self.get_selected_export_format())

        def _do_export() -> None:
            self._run_export_all(completed_items, out_path, config)

        if sync:
            _do_export()
            return None

        thread = threading.Thread(target=_do_export, name="ExportAllWorker", daemon=True)
        self._export_thread = thread
        thread.start()
        return thread

    def _run_export_all(
        self,
        completed_items: List[QueueItem],
        out_path: Path,
        config: JobConfig,
    ) -> None:
        """Internal export loop running on background worker thread or synchronously."""
        total_saved = 0
        used_stems: Set[str] = set()
        total_docs = len(completed_items)
        failed_docs = 0
        last_err = None
        try:
            active_exts = _FORMAT_EXTENSIONS.get(config.output_format, (".md", ".json", ".docx"))
            for idx, it in enumerate(completed_items, start=1):
                if self.is_shutting_down() or self.shutdown_event.is_set():
                    return
                if it.result is None:
                    raise RuntimeError(f"Queue item {it.file_path.name} marked completed but missing OCRResult")
                try:
                    stem_resolver = self.resolve_unique_stem or resolve_unique_stem
                    unique_stem = stem_resolver(
                        it.file_path.stem,
                        output_dir=out_path,
                        used_stems=used_stems,
                        extensions=active_exts,
                    )
                    do_save = self.save_artifacts or save_artifacts
                    saved = do_save(it.result, config=config, output_dir=out_path, base_name=unique_stem)
                    total_saved += len(saved)
                except Exception as doc_exc:
                    failed_docs += 1
                    last_err = doc_exc
                    logger.warning("Export error on %s: %s", it.file_path.name, doc_exc)
                self.safe_after(
                    0,
                    lambda i=idx, n=total_docs: self.update_footer(f"Exporting {i}/{n} documents..."),
                )

            def _on_finish() -> None:
                if failed_docs > 0:
                    self.update_footer(
                        f"Export completed: {total_docs - failed_docs}/{total_docs} succeeded "
                        f"({failed_docs} failed: {self.format_error(last_err)})"
                    )
                else:
                    self.update_footer(f"Exported {total_docs} documents ({total_saved} files) to {out_path.name}")
                if self.btn_export_all is not None:
                    self.btn_export_all.configure(text="Exported All!")
                self.after(1200, self.reset_export_all_button)

            self.safe_after(0, _on_finish)
        except Exception as exc:
            logger.warning("Export All error: %s", exc)
            self.safe_after(0, lambda e=exc: self.update_footer(f"Export All error: {self.format_error(e)}"))
            self.safe_after(0, self.reset_export_all_button)
        finally:
            self._is_exporting = False

    def reset_export_selected_button(self) -> None:
        """Reset the Export Selected button text after export completes."""
        if self.is_shutting_down():
            return
        if self.btn_export_selected is not None:
            self.btn_export_selected.configure(text="Export Selected")
        if self.on_action_buttons_changed is not None:
            self.on_action_buttons_changed()
        elif self.queue_manager is not None:
            selected_id = self.queue_manager.selected_item_id
            selected_item = self.queue_manager.items.get(selected_id) if selected_id else None
            selected_completed = (
                selected_item is not None
                and selected_item.status in (QueueItemStatus.SUCCESS, QueueItemStatus.CANCELLED)
                and selected_item.result is not None
                and len(selected_item.result.pages) > 0
            )
            completed_count = sum(
                1
                for it in self.queue_manager.items.values()
                if it.status == QueueItemStatus.SUCCESS and it.result is not None
            )
            self.update_buttons(selected_completed=selected_completed, completed_count=completed_count)

    def reset_export_all_button(self) -> None:
        """Reset the Export All button text and enabled state after export completes."""
        if self.is_shutting_down():
            return
        completed_count = 0
        if self.queue_manager is not None:
            completed_count = sum(
                1
                for it in self.queue_manager.items.values()
                if it.status == QueueItemStatus.SUCCESS and it.result is not None
            )
        if self.btn_export_all is not None:
            self.btn_export_all.configure(
                text="Export All",
                state="normal" if completed_count > 0 else "disabled",
            )

    def wait_for_export(self, timeout: float = 3.0) -> None:
        """Wait for any active background export thread to complete and drain main loop callbacks."""
        if self._export_thread and self._export_thread.is_alive():
            self._export_thread.join(timeout=timeout)
        self.drain_ui_callbacks()
        if self.update_ui is not None:
            try:
                self.update_ui()
            except Exception as exc:
                logger.debug("Failed to update UI after export wait: %s", exc)
