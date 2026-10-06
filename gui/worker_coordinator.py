"""Background OCR worker thread execution and event dispatch coordinator.

Manages the dedicated OCR background worker thread, result event queue drainage,
progress bar state (determinate / indeterminate), per-document cancel tokens,
inter-document settings staging, and graceful worker shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
import queue
import sys
import threading
import traceback
from typing import Any, Callable, Optional

from config.settings import Settings
from core.client import resolve_chat_endpoint
from core.engine import JobStatus, OCRResult, PageResult
from core.models import JobConfig
from gui.queue_manager import QueueItem, QueueItemStatus
from gui.theme import (
    COLOR_STATUS_CANCELLED,
    COLOR_STATUS_FAILED,
    COLOR_STATUS_PARTIAL,
    COLOR_STATUS_PROCESSING,
    COLOR_STATUS_SUCCESS,
    COLOR_TEXT_MUTED,
)

logger = logging.getLogger(__name__)


class WorkerEventType(str, Enum):
    """Event types posted from the background worker thread to the main UI thread."""
    STARTED = "STARTED"
    PAGE_PROGRESS = "PAGE_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    WORKER_CRASHED = "WORKER_CRASHED"


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


class WorkerCoordinator:
    """Coordinates background OCR document processing, event queue drainage, and UI progress."""

    def __init__(
        self,
        engine: Any,
        settings: Any,
        queue_manager: Any,
        task_queue: Optional[queue.Queue[Optional[Path]]] = None,
        result_queue: Optional[queue.Queue[WorkerEvent]] = None,
        export_controller: Optional[Any] = None,
        image_preview: Optional[Any] = None,
        safe_after: Optional[Callable[[int, Any], None]] = None,
        after: Optional[Callable[[int, Any], str]] = None,
        after_cancel: Optional[Callable[[str], None]] = None,
        is_shutting_down: Optional[Callable[[], bool]] = None,
        shutdown_event: Optional[threading.Event] = None,
        drain_ui_callbacks: Optional[Callable[[], None]] = None,
        update_footer: Optional[Callable[[Optional[str]], None]] = None,
        render_preview: Optional[Callable[[QueueItem], None]] = None,
        update_action_buttons: Optional[Callable[[], None]] = None,
        format_queue_item_meta: Optional[Callable[[QueueItem], str]] = None,
        progress_bar: Optional[Any] = None,
        lbl_page_counter: Optional[Any] = None,
        lbl_progress_info: Optional[Any] = None,
        btn_cancel: Optional[Any] = None,
        poll_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._queue_manager = queue_manager
        self.export_controller = export_controller
        self.image_preview = image_preview
        self.safe_after = safe_after
        self.after = after
        self.after_cancel = after_cancel
        self.is_shutting_down = is_shutting_down
        self.shutdown_event = shutdown_event
        self.drain_ui_callbacks = drain_ui_callbacks
        self.update_footer = update_footer
        self.render_preview = render_preview
        self.update_action_buttons = update_action_buttons
        self.format_queue_item_meta = format_queue_item_meta
        self.progress_bar = progress_bar
        self.lbl_page_counter = lbl_page_counter
        self.lbl_progress_info = lbl_progress_info
        self.btn_cancel = btn_cancel
        self.poll_callback = poll_callback

        self._task_queue: queue.Queue[Optional[Path]] = task_queue if task_queue is not None else queue.Queue()
        self._result_queue: queue.Queue[WorkerEvent] = result_queue if result_queue is not None else queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._poll_id: Optional[str] = None
        self._current_cancel_event: Optional[threading.Event] = None
        self._pending_engine_settings: Optional[Settings] = None
        self._success_count: int = 0
        self._failed_count: int = 0
        self._progress_indeterminate: bool = False

    @property
    def engine(self) -> Any:
        return self._engine

    @engine.setter
    def engine(self, value: Any) -> None:
        self._engine = value

    @property
    def settings(self) -> Any:
        return self._settings

    @settings.setter
    def settings(self, value: Any) -> None:
        self._settings = value

    @property
    def queue_manager(self) -> Any:
        return self._queue_manager

    @queue_manager.setter
    def queue_manager(self, value: Any) -> None:
        self._queue_manager = value

    @property
    def task_queue(self) -> queue.Queue[Optional[Path]]:
        return self._task_queue

    @task_queue.setter
    def task_queue(self, value: queue.Queue[Optional[Path]]) -> None:
        self._task_queue = value

    @property
    def result_queue(self) -> queue.Queue[WorkerEvent]:
        return self._result_queue

    @result_queue.setter
    def result_queue(self, value: queue.Queue[WorkerEvent]) -> None:
        self._result_queue = value

    @property
    def worker_thread(self) -> Optional[threading.Thread]:
        return self._worker_thread

    @worker_thread.setter
    def worker_thread(self, value: Optional[threading.Thread]) -> None:
        self._worker_thread = value

    @property
    def poll_id(self) -> Optional[str]:
        return self._poll_id

    @poll_id.setter
    def poll_id(self, value: Optional[str]) -> None:
        self._poll_id = value

    @property
    def current_cancel_event(self) -> Optional[threading.Event]:
        return self._current_cancel_event

    @current_cancel_event.setter
    def current_cancel_event(self, value: Optional[threading.Event]) -> None:
        self._current_cancel_event = value

    @property
    def pending_engine_settings(self) -> Optional[Settings]:
        return self._pending_engine_settings

    @pending_engine_settings.setter
    def pending_engine_settings(self, value: Optional[Settings]) -> None:
        self._pending_engine_settings = value

    @property
    def success_count(self) -> int:
        return self._success_count

    @success_count.setter
    def success_count(self, value: int) -> None:
        self._success_count = value

    @property
    def failed_count(self) -> int:
        return self._failed_count

    @failed_count.setter
    def failed_count(self, value: int) -> None:
        self._failed_count = value

    @property
    def progress_indeterminate(self) -> bool:
        return self._progress_indeterminate

    @progress_indeterminate.setter
    def progress_indeterminate(self, value: bool) -> None:
        self._progress_indeterminate = value

    def start(self) -> None:
        """Start background worker thread and start polling result queue."""
        self._worker_thread = threading.Thread(
            target=self.worker_loop,
            name="OCRWorkerThread",
            daemon=True,
        )
        self._worker_thread.start()
        self.process_result_queue()

    def worker_loop(self) -> None:
        """Dedicated background worker loop processing OCR jobs from the task queue."""
        try:
            while self.shutdown_event is None or not self.shutdown_event.is_set():
                try:
                    item = self._task_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if item is None or (self.shutdown_event is not None and self.shutdown_event.is_set()):
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
                    # Apply any pending settings updates at document boundary
                    self.apply_pending_engine_settings()
                    engine = self.engine
                    settings = self.settings
                    effective_settings = (
                        engine.settings
                        if hasattr(engine, "settings") and isinstance(engine.settings, Settings)
                        else settings
                    )
                    job_cfg = JobConfig(
                        max_pages=effective_settings.max_pages,
                        dpi=effective_settings.dpi,
                        max_image_dimension=effective_settings.max_image_dimension,
                    )

                    # Pre-flight startup self-test before processing first document in session
                    if hasattr(engine, "verify_backend"):
                        engine.verify_backend()

                    # Post STARTED event with effective job dpi
                    self._result_queue.put(
                        WorkerEvent(
                            event_type=WorkerEventType.STARTED,
                            file_path=file_path_str,
                            processed_dpi=job_cfg.dpi,
                        )
                    )

                    result = engine.process_document(
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
                    if self.shutdown_event is None or not self.shutdown_event.is_set():
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
            except Exception as exc:
                logger.debug("Failed to enqueue WORKER_CRASHED event: %s", exc)

    def process_result_queue(self) -> None:
        """Periodic timer callback running on the main thread to drain worker events."""
        if self.drain_ui_callbacks is not None:
            self.drain_ui_callbacks()

        while True:
            try:
                event = self._result_queue.get_nowait()
            except queue.Empty:
                break

            self.handle_worker_event(event)

        if self.is_shutting_down is None or not self.is_shutting_down():
            is_active = (not self._task_queue.empty()) or (self._current_cancel_event is not None)
            poll_interval_ms = 50 if is_active else 250
            if self.after is not None:
                callback = self.poll_callback if self.poll_callback is not None else self.process_result_queue
                self._poll_id = self.after(poll_interval_ms, callback)

    def stop_indeterminate_progress(self) -> None:
        """Stop indeterminate progress bar animation and switch back to determinate mode."""
        if self._progress_indeterminate:
            if self.progress_bar is not None:
                try:
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                except Exception as exc:
                    logger.debug("Failed to stop indeterminate progress bar: %s", exc)
            self._progress_indeterminate = False

    def handle_worker_event(self, event: WorkerEvent) -> None:
        """Process a single worker event on the main thread and update state/UI."""
        qm = self.queue_manager
        items = qm.items if qm is not None and hasattr(qm, "items") else {}
        item = items.get(event.file_path)

        def _format_item_meta(target_item: QueueItem) -> str:
            if self.format_queue_item_meta is not None:
                return self.format_queue_item_meta(target_item)
            if qm is not None and hasattr(qm, "format_item_meta"):
                return qm.format_item_meta(target_item)
            return ""

        if event.event_type == WorkerEventType.STARTED:
            print(f"[GUI Worker] Started processing: {event.file_path}")
            if self.progress_bar is not None:
                try:
                    self.progress_bar.configure(mode="indeterminate")
                    self.progress_bar.start()
                    self._progress_indeterminate = True
                except Exception as exc:
                    logger.debug("Failed to start indeterminate progress bar: %s", exc)
                    self.progress_bar.set(0.0)
            else:
                self._progress_indeterminate = True

            if self.lbl_page_counter is not None:
                self.lbl_page_counter.configure(text="0 / ...")
            if self.lbl_progress_info is not None:
                self.lbl_progress_info.configure(text=f"Processing {Path(event.file_path).name}...")

            if item:
                item.status = QueueItemStatus.PROCESSING
                if event.processed_dpi is not None:
                    item.processed_dpi = event.processed_dpi
                if item.badge_label:
                    item.badge_label.configure(text="●", text_color=COLOR_STATUS_PROCESSING)
                if item.detail_label:
                    item.detail_label.configure(
                        text=_format_item_meta(item),
                        text_color=COLOR_STATUS_PROCESSING,
                    )
            if self.update_footer is not None:
                self.update_footer(f"Processing: {Path(event.file_path).name}")

        elif event.event_type == WorkerEventType.PAGE_PROGRESS:
            self.stop_indeterminate_progress()
            cur = event.current_page
            tot = max(1, event.total_pages)
            fraction = min(1.0, max(0.0, cur / tot))
            if self.progress_bar is not None:
                self.progress_bar.set(fraction)
            if self.lbl_page_counter is not None:
                self.lbl_page_counter.configure(text=f"Page {cur} of {tot}")
            if self.lbl_progress_info is not None:
                self.lbl_progress_info.configure(text=f"Processing {Path(event.file_path).name} ({int(fraction * 100)}%)")
            if self.update_footer is not None:
                self.update_footer(f"Processing: {Path(event.file_path).name} (Page {cur}/{tot})")

            if item:
                item.status = QueueItemStatus.PROCESSING
                if item.result is None:
                    item.result = OCRResult(file_path=item.file_path, status=JobStatus.SUCCESS)
                if event.page_result:
                    if not any(p.page_num == event.page_result.page_num for p in item.result.pages):
                        item.result.pages.append(event.page_result)

                selected_id = getattr(qm, "selected_item_id", None)
                if selected_id == item.item_id and self.render_preview is not None:
                    self.render_preview(item)
            return

        elif event.event_type == WorkerEventType.COMPLETED:
            self.stop_indeterminate_progress()
            duration = event.result.total_duration if event.result else 0.0
            status_val = event.result.status.value if event.result else "SUCCESS"
            total_pages = len(event.result.pages) if event.result and event.result.pages else 1
            print(f"[GUI Worker] Completed processing: {event.file_path} ({duration:.1f}s)")
            self._success_count += 1
            if self.progress_bar is not None:
                self.progress_bar.set(1.0)
            if self.lbl_page_counter is not None:
                self.lbl_page_counter.configure(text=f"{total_pages}/{total_pages} done")
            if self.lbl_progress_info is not None:
                self.lbl_progress_info.configure(text=f"Completed {Path(event.file_path).name}")

            if item:
                item.status = QueueItemStatus.SUCCESS
                item.result = event.result
                item.duration = duration
                if item.badge_label:
                    badge_color = COLOR_STATUS_SUCCESS if status_val == "SUCCESS" else COLOR_STATUS_PARTIAL
                    item.badge_label.configure(text="●", text_color=badge_color)
                if item.detail_label:
                    item.detail_label.configure(
                        text=_format_item_meta(item),
                        text_color=COLOR_TEXT_MUTED,
                    )
            if self.update_footer is not None:
                self.update_footer(f"Done: {Path(event.file_path).name} ({status_val})")

        elif event.event_type == WorkerEventType.FAILED:
            self.stop_indeterminate_progress()
            err_msg = event.error or "Error"
            print(f"[GUI Worker] Failed processing: {event.file_path} ({err_msg})")
            self._failed_count += 1
            if self.progress_bar is not None:
                self.progress_bar.set(0.0)
            if self.lbl_page_counter is not None:
                self.lbl_page_counter.configure(text="Failed")
            if self.lbl_progress_info is not None:
                self.lbl_progress_info.configure(text=f"Failed: {Path(event.file_path).name}")

            if item:
                item.status = QueueItemStatus.FAILED
                item.result = event.result
                item.error = err_msg
                if item.badge_label:
                    item.badge_label.configure(text="●", text_color=COLOR_STATUS_FAILED)
                if item.detail_label:
                    item.detail_label.configure(
                        text=_format_item_meta(item),
                        text_color=COLOR_STATUS_FAILED,
                    )
            if self.update_footer is not None:
                self.update_footer(f"Failed: {Path(event.file_path).name} - {err_msg}")

        elif event.event_type == WorkerEventType.CANCELLED:
            self.stop_indeterminate_progress()
            err_msg = event.error or "Cancelled"
            print(f"[GUI Worker] Cancelled processing: {event.file_path} ({err_msg})")
            if self.progress_bar is not None:
                self.progress_bar.set(0.0)
            if self.lbl_page_counter is not None:
                self.lbl_page_counter.configure(text="Cancelled")
            if self.lbl_progress_info is not None:
                self.lbl_progress_info.configure(text=f"Cancelled: {Path(event.file_path).name}")

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
                        text=_format_item_meta(item),
                        text_color=COLOR_STATUS_CANCELLED,
                    )
            if self.update_footer is not None:
                self.update_footer(f"Cancelled: {Path(event.file_path).name}")

        elif event.event_type == WorkerEventType.WORKER_CRASHED:
            self.stop_indeterminate_progress()
            print(f"[GUI Worker] FATAL: Worker thread crashed: {event.error}", file=sys.stderr)
            sys.stderr.flush()
            if self.progress_bar is not None:
                self.progress_bar.set(0.0)
            if self.lbl_page_counter is not None:
                self.lbl_page_counter.configure(text="Error")
            if self.update_footer is not None:
                self.update_footer(f"Fatal Worker Error: {event.error}")

        # RACE-FREE SELECTION HANDLING:
        # Only refresh preview pane if finished item is still active selection; else update action buttons
        selected_id = getattr(qm, "selected_item_id", None)
        if item and selected_id == item.item_id:
            if self.render_preview is not None:
                self.render_preview(item)
        else:
            if self.update_action_buttons is not None:
                self.update_action_buttons()

    def cancel_current(self) -> None:
        """Signal the current in-flight job to cancel after the current page finishes."""
        if self._current_cancel_event and not self._current_cancel_event.is_set():
            self._current_cancel_event.set()
            if self.btn_cancel is not None:
                self.btn_cancel.configure(text="Cancelling...", state="disabled")
            if self.update_footer is not None:
                self.update_footer("Cancelling after current page...")

    def apply_pending_engine_settings(self) -> None:
        """Apply pending settings updates to engine and vision client at safe document boundary."""
        pending_s = self._pending_engine_settings
        if pending_s is not None:
            self._pending_engine_settings = None
            engine = self.engine
            if hasattr(engine, "client") and engine.client is not None:
                engine.client.endpoint = resolve_chat_endpoint(pending_s.local_endpoint)
                engine.client.settings = pending_s
            if hasattr(engine, "settings"):
                engine.settings = pending_s
            self.settings = pending_s

    def queue_pending_settings(self, new_settings: Settings) -> None:
        """Queue settings for safe inter-document update, applying immediately if idle."""
        self._pending_engine_settings = new_settings
        engine = self.engine
        if hasattr(engine, "invalidate_backend_verification"):
            engine.invalidate_backend_verification()
        if self._current_cancel_event is None:
            self.apply_pending_engine_settings()

    def shutdown(self, timeout: float = 3.0) -> None:
        """Cleanly cancel poll timer, drain unstarted tasks, signal worker, and join thread."""
        if self._poll_id is not None and self.after_cancel is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception as exc:
                logger.debug("Failed to cancel worker coordinator poll timer: %s", exc)
            self._poll_id = None

        while not self._task_queue.empty():
            try:
                self._task_queue.get_nowait()
                self._task_queue.task_done()
            except (queue.Empty, ValueError):
                break

        try:
            self._task_queue.put_nowait(None)
        except (queue.Full, ValueError) as exc:
            logger.debug("Failed to enqueue shutdown sentinel into task queue: %s", exc)

        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
