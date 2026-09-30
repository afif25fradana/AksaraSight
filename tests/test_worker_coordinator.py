"""Isolated unit tests for gui/worker_coordinator.py.

Tests WorkerCoordinator background worker loop, event dispatch, adaptive polling backoff,
cancellation signaling, staged settings deferral, and error/crash handling.
Runs 100% headless without requiring ctk.CTk or an active display server.
"""

from __future__ import annotations

from pathlib import Path
import queue
import threading
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, NonCallableMock, patch

import pytest

from config.settings import Settings
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
from gui.worker_coordinator import WorkerCoordinator, WorkerEvent, WorkerEventType


# ==============================================================================
# Headless Widget Fakes
# ==============================================================================


class FakeProgressBar:
    """Duck-typed progress bar widget fake tracking configure, start, stop, and set."""

    def __init__(self, value: float = 0.0, mode: str = "determinate") -> None:
        self.value = value
        self.mode = mode
        self.started = False
        self.stopped = False

    def configure(self, **kwargs: Any) -> None:
        if "mode" in kwargs:
            self.mode = kwargs["mode"]

    def start(self) -> None:
        self.started = True
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        self.started = False

    def set(self, val: float) -> None:
        self.value = val

    def get(self) -> float:
        return self.value


class FakeLabel:
    """Duck-typed label widget fake tracking text and color."""

    def __init__(self, text: str = "", text_color: Any = None) -> None:
        self.text = text
        self.text_color = text_color

    def configure(self, **kwargs: Any) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]
        if "text_color" in kwargs:
            self.text_color = kwargs["text_color"]

    def cget(self, key: str) -> Any:
        return getattr(self, key, None)


class FakeButton:
    """Duck-typed button widget fake tracking text and state."""

    def __init__(self, text: str = "Cancel", state: str = "normal") -> None:
        self.text = text
        self.state = state

    def configure(self, **kwargs: Any) -> None:
        if "text" in kwargs:
            self.text = kwargs["text"]
        if "state" in kwargs:
            self.state = kwargs["state"]

    def cget(self, key: str) -> Any:
        return getattr(self, key, None)


class FakeQueueManager:
    """Duck-typed QueueManager fake providing items dict and selection."""

    def __init__(self, items: Optional[Dict[str, QueueItem]] = None) -> None:
        self._items: Dict[str, QueueItem] = items if items is not None else {}
        self.selected_item_id: Optional[str] = None

    @property
    def items(self) -> Dict[str, QueueItem]:
        return self._items

    def format_item_meta(self, item: QueueItem) -> str:
        return f"{item.file_size_str} • {item.processed_dpi} DPI"


# ==============================================================================
# Helper Factories
# ==============================================================================


def _create_fake_item(file_path: Path, item_id: Optional[str] = None) -> QueueItem:
    """Create a QueueItem with fake labels attached for event testing."""
    item = QueueItem(
        item_id=item_id or str(file_path),
        file_path=file_path,
        status=QueueItemStatus.QUEUED,
        file_size_str="1.2 MB",
    )
    item.badge_label = FakeLabel(text="●", text_color=COLOR_TEXT_MUTED)
    item.detail_label = FakeLabel(text="1.2 MB", text_color=COLOR_TEXT_MUTED)
    return item


# ==============================================================================
# Unit Tests
# ==============================================================================


def test_coordinator_init_defaults() -> None:
    """WorkerCoordinator initializes queues, state counters, and null threads by default."""
    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=None,
    )
    assert isinstance(coord.task_queue, queue.Queue)
    assert isinstance(coord.result_queue, queue.Queue)
    assert coord.worker_thread is None
    assert coord.poll_id is None
    assert coord.current_cancel_event is None
    assert coord.pending_engine_settings is None
    assert coord.success_count == 0
    assert coord.failed_count == 0
    assert coord.progress_indeterminate is False


def test_coordinator_custom_queues_and_accessors() -> None:
    """WorkerCoordinator preserves injected queue instances and supports full facade access."""
    t_q: queue.Queue = queue.Queue()
    r_q: queue.Queue = queue.Queue()
    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=None,
        task_queue=t_q,
        result_queue=r_q,
    )
    assert coord.task_queue is t_q
    assert coord.result_queue is r_q

    # Property setters
    new_t_q: queue.Queue = queue.Queue()
    new_r_q: queue.Queue = queue.Queue()
    coord.task_queue = new_t_q
    coord.result_queue = new_r_q
    assert coord.task_queue is new_t_q
    assert coord.result_queue is new_r_q

    coord.poll_id = "after#42"
    assert coord.poll_id == "after#42"

    evt = threading.Event()
    coord.current_cancel_event = evt
    assert coord.current_cancel_event is evt

    new_s = Settings(dpi=200)
    coord.pending_engine_settings = new_s
    assert coord.pending_engine_settings is new_s

    coord.success_count = 5
    coord.failed_count = 2
    coord.progress_indeterminate = True
    assert coord.success_count == 5
    assert coord.failed_count == 2
    assert coord.progress_indeterminate is True


def test_coordinator_dynamic_property_resolution() -> None:
    """Dynamic resolution resolves static objects, callables, and protects NonCallableMock."""
    # Static
    s1 = Settings(dpi=150)
    coord = WorkerCoordinator(engine="engine1", settings=s1, queue_manager="qm1")
    assert coord.engine == "engine1"
    assert coord.settings == s1
    assert coord.queue_manager == "qm1"

    # Callable / lambda
    s2 = Settings(dpi=300)
    coord2 = WorkerCoordinator(
        engine=lambda: "resolved_engine",
        settings=lambda: s2,
        queue_manager=lambda: "resolved_qm",
    )
    assert coord2.engine == "resolved_engine"
    assert coord2.settings == s2
    assert coord2.queue_manager == "resolved_qm"

    # NonCallableMock (treat as direct object, do not attempt to invoke as factory)
    mock_engine = NonCallableMock()
    coord3 = WorkerCoordinator(engine=mock_engine, settings=s1, queue_manager=None)
    assert coord3.engine is mock_engine


def test_coordinator_start_lifecycle() -> None:
    """start() spawns named daemon thread OCRWorkerThread and schedules initial poll."""
    after_calls: List[tuple] = []

    def fake_after(ms: int, cb: Any) -> str:
        after_calls.append((ms, cb))
        return "timer#1"

    shutdown_evt = threading.Event()
    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=None,
        after=fake_after,
        shutdown_event=shutdown_evt,
    )
    coord.start()

    th = coord.worker_thread
    assert th is not None
    assert th.name == "OCRWorkerThread"
    assert th.daemon is True
    assert th.is_alive()
    assert len(after_calls) == 1
    assert after_calls[0][0] == 250

    # Clean shutdown
    coord.shutdown(timeout=1.0)
    assert not th.is_alive()


def test_coordinator_handle_worker_event_started() -> None:
    """STARTED event sets indeterminate progress, updates labels, status, and DPI."""
    p_bar = FakeProgressBar()
    lbl_pages = FakeLabel()
    lbl_info = FakeLabel()
    footer_msgs: List[str] = []

    test_file = Path("sample_doc.pdf")
    item = _create_fake_item(test_file)
    qm = FakeQueueManager({str(test_file): item})

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=qm,
        progress_bar=p_bar,
        lbl_page_counter=lbl_pages,
        lbl_progress_info=lbl_info,
        update_footer=footer_msgs.append,
    )

    event = WorkerEvent(
        event_type=WorkerEventType.STARTED,
        file_path=str(test_file),
        processed_dpi=200,
    )
    coord.handle_worker_event(event)

    assert p_bar.mode == "indeterminate"
    assert p_bar.started is True
    assert coord.progress_indeterminate is True
    assert lbl_pages.text == "0 / ..."
    assert "sample_doc.pdf" in lbl_info.text
    assert item.status == QueueItemStatus.PROCESSING
    assert item.processed_dpi == 200
    assert item.badge_label.text_color == COLOR_STATUS_PROCESSING
    assert item.detail_label.text_color == COLOR_STATUS_PROCESSING
    assert any("Processing: sample_doc.pdf" in m for m in footer_msgs)


def test_coordinator_handle_worker_event_page_progress() -> None:
    """PAGE_PROGRESS updates fraction, page count, and renders preview if selected."""
    p_bar = FakeProgressBar(mode="indeterminate")
    p_bar.started = True
    lbl_pages = FakeLabel()
    lbl_info = FakeLabel()
    preview_rendered: List[QueueItem] = []

    test_file = Path("doc.pdf")
    item = _create_fake_item(test_file)
    qm = FakeQueueManager({str(test_file): item})
    qm.selected_item_id = str(test_file)  # Active selection

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=qm,
        progress_bar=p_bar,
        lbl_page_counter=lbl_pages,
        lbl_progress_info=lbl_info,
        render_preview=preview_rendered.append,
    )
    coord.progress_indeterminate = True

    page_res = PageResult(page_num=1, markdown="Page 1 text")
    event = WorkerEvent(
        event_type=WorkerEventType.PAGE_PROGRESS,
        file_path=str(test_file),
        current_page=1,
        total_pages=4,
        page_result=page_res,
    )
    coord.handle_worker_event(event)

    assert p_bar.stopped is True
    assert coord.progress_indeterminate is False
    assert p_bar.value == 0.25
    assert lbl_pages.text == "Page 1 of 4"
    assert "25%" in lbl_info.text
    assert item.result is not None
    assert len(item.result.pages) == 1
    assert item.result.pages[0].markdown == "Page 1 text"
    assert len(preview_rendered) == 1
    assert preview_rendered[0] is item


def test_coordinator_handle_worker_event_completed() -> None:
    """COMPLETED increments success count, sets 1.0 progress, updates item and badge."""
    p_bar = FakeProgressBar()
    lbl_pages = FakeLabel()
    lbl_info = FakeLabel()
    action_btns_updated: List[bool] = []

    test_file = Path("doc.pdf")
    item = _create_fake_item(test_file)
    qm = FakeQueueManager({str(test_file): item})
    qm.selected_item_id = "other_doc.pdf"  # Not selected

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=qm,
        progress_bar=p_bar,
        lbl_page_counter=lbl_pages,
        lbl_progress_info=lbl_info,
        update_action_buttons=lambda: action_btns_updated.append(True),
    )

    ocr_res = OCRResult(
        file_path=test_file,
        status=JobStatus.SUCCESS,
        total_duration=3.5,
        pages=[PageResult(page_num=1, markdown="Done")],
    )
    event = WorkerEvent(
        event_type=WorkerEventType.COMPLETED,
        file_path=str(test_file),
        result=ocr_res,
    )
    coord.handle_worker_event(event)

    assert coord.success_count == 1
    assert p_bar.value == 1.0
    assert lbl_pages.text == "1/1 done"
    assert "Completed doc.pdf" in lbl_info.text
    assert item.status == QueueItemStatus.SUCCESS
    assert item.duration == 3.5
    assert item.badge_label.text_color == COLOR_STATUS_SUCCESS
    assert len(action_btns_updated) == 1


def test_coordinator_handle_worker_event_failed() -> None:
    """FAILED increments failed count, sets progress 0.0, records error on item."""
    p_bar = FakeProgressBar(value=0.5)
    lbl_pages = FakeLabel()
    lbl_info = FakeLabel()

    test_file = Path("fail.pdf")
    item = _create_fake_item(test_file)
    qm = FakeQueueManager({str(test_file): item})

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=qm,
        progress_bar=p_bar,
        lbl_page_counter=lbl_pages,
        lbl_progress_info=lbl_info,
    )

    event = WorkerEvent(
        event_type=WorkerEventType.FAILED,
        file_path=str(test_file),
        error="Corrupt file format",
    )
    coord.handle_worker_event(event)

    assert coord.failed_count == 1
    assert p_bar.value == 0.0
    assert lbl_pages.text == "Failed"
    assert "Failed: fail.pdf" in lbl_info.text
    assert item.status == QueueItemStatus.FAILED
    assert item.error == "Corrupt file format"
    assert item.badge_label.text_color == COLOR_STATUS_FAILED


def test_coordinator_handle_worker_event_cancelled() -> None:
    """CANCELLED sets item status to CANCELLED and records cancellation duration."""
    p_bar = FakeProgressBar(value=0.75)
    lbl_pages = FakeLabel()
    lbl_info = FakeLabel()

    test_file = Path("cancel.pdf")
    item = _create_fake_item(test_file)
    qm = FakeQueueManager({str(test_file): item})

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=qm,
        progress_bar=p_bar,
        lbl_page_counter=lbl_pages,
        lbl_progress_info=lbl_info,
    )

    event = WorkerEvent(
        event_type=WorkerEventType.CANCELLED,
        file_path=str(test_file),
        error="Cancelled by user",
    )
    coord.handle_worker_event(event)

    assert p_bar.value == 0.0
    assert lbl_pages.text == "Cancelled"
    assert item.status == QueueItemStatus.CANCELLED
    assert item.error == "Cancelled by user"
    assert item.badge_label.text_color == COLOR_STATUS_CANCELLED


def test_coordinator_handle_worker_event_worker_crashed() -> None:
    """WORKER_CRASHED stops indeterminate bar, resets progress, and updates footer."""
    p_bar = FakeProgressBar()
    lbl_pages = FakeLabel()
    footer_msgs: List[str] = []

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=None,
        progress_bar=p_bar,
        lbl_page_counter=lbl_pages,
        update_footer=footer_msgs.append,
    )

    event = WorkerEvent(
        event_type=WorkerEventType.WORKER_CRASHED,
        file_path="",
        error="Uncaught fatal crash",
    )
    coord.handle_worker_event(event)

    assert p_bar.value == 0.0
    assert lbl_pages.text == "Error"
    assert any("Fatal Worker Error: Uncaught fatal crash" in m for m in footer_msgs)


def test_coordinator_adaptive_polling_intervals() -> None:
    """process_result_queue drains events and schedules 50ms (active) or 250ms (idle)."""
    drain_called = [False]
    after_calls: List[tuple] = []

    def fake_after(ms: int, cb: Any) -> str:
        after_calls.append((ms, cb))
        return f"timer#{len(after_calls)}"

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=None,
        after=fake_after,
        drain_ui_callbacks=lambda: drain_called.__setitem__(0, True),
    )

    # 1. Idle state (queue empty, cancel event None) -> 250ms
    coord.process_result_queue()
    assert drain_called[0] is True
    assert len(after_calls) == 1
    assert after_calls[0][0] == 250

    # 2. Active state with items in task_queue -> 50ms
    coord.task_queue.put(Path("doc1.pdf"))
    coord.process_result_queue()
    assert len(after_calls) == 2
    assert after_calls[1][0] == 50
    coord.task_queue.get()  # Clear item

    # 3. Active state with cancel_event active -> 50ms
    coord.current_cancel_event = threading.Event()
    coord.process_result_queue()
    assert len(after_calls) == 3
    assert after_calls[2][0] == 50
    coord.current_cancel_event = None

    # 4. Shutting down -> does not schedule next timer
    shutting_down = True
    coord.is_shutting_down = lambda: shutting_down
    coord.process_result_queue()
    assert len(after_calls) == 3  # No new call scheduled


def test_coordinator_cancel_current() -> None:
    """cancel_current signals current_cancel_event, disables cancel button, and logs footer."""
    btn = FakeButton(text="Cancel", state="normal")
    footer_msgs: List[str] = []

    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=None,
        btn_cancel=btn,
        update_footer=footer_msgs.append,
    )

    # When no active cancel event, cancel_current is a safe no-op
    coord.cancel_current()
    assert btn.text == "Cancel"

    # With active cancel event
    evt = threading.Event()
    coord.current_cancel_event = evt
    coord.cancel_current()

    assert evt.is_set()
    assert btn.text == "Cancelling..."
    assert btn.state == "disabled"
    assert any("Cancelling after current page..." in m for m in footer_msgs)


def test_coordinator_queue_pending_settings_immediate_when_idle() -> None:
    """queue_pending_settings applies immediately when no document is in-flight."""
    mock_engine = MagicMock()
    mock_client = MagicMock()
    mock_engine.client = mock_client

    coord = WorkerCoordinator(
        engine=mock_engine,
        settings=Settings(dpi=150, local_endpoint="http://127.0.0.1:11434"),
        queue_manager=None,
    )

    new_s = Settings(dpi=300, local_endpoint="http://127.0.0.1:8000")
    coord.queue_pending_settings(new_s)

    assert mock_engine.invalidate_backend_verification.called
    assert mock_engine.settings == new_s
    assert coord.settings == new_s
    assert coord.pending_engine_settings is None
    assert mock_client.endpoint == "http://127.0.0.1:8000/v1/chat/completions"


def test_coordinator_queue_pending_settings_deferred_when_in_flight() -> None:
    """queue_pending_settings stores settings during active job, applies at boundary."""
    mock_engine = MagicMock()
    mock_engine.client = MagicMock()

    s_orig = Settings(dpi=150)
    coord = WorkerCoordinator(
        engine=mock_engine,
        settings=s_orig,
        queue_manager=None,
    )

    # Simulate active in-flight document
    coord.current_cancel_event = threading.Event()

    new_s = Settings(dpi=300)
    coord.queue_pending_settings(new_s)

    # Invalidation called, but engine settings NOT changed yet
    assert mock_engine.invalidate_backend_verification.called
    assert coord.pending_engine_settings == new_s
    assert coord.settings == s_orig

    # Simulate document boundary completion
    coord.current_cancel_event = None
    coord.apply_pending_engine_settings()

    assert coord.settings == new_s
    assert mock_engine.settings == new_s
    assert coord.pending_engine_settings is None


def test_coordinator_worker_loop_end_to_end_success(tmp_path: Path) -> None:
    """Worker loop processes item via engine, emits STARTED and COMPLETED events, exits cleanly."""
    doc_path = tmp_path / "test.pdf"
    doc_path.write_bytes(b"%PDF-fake")

    mock_engine = MagicMock()
    expected_result = OCRResult(
        file_path=doc_path,
        status=JobStatus.SUCCESS,
        total_duration=1.2,
        pages=[PageResult(page_num=1, markdown="Page 1 text")],
    )

    def fake_process_doc(path: Path, config: Any = None, progress_callback: Any = None, **kwargs: Any) -> OCRResult:
        if progress_callback:
            progress_callback(1, 1, PageResult(page_num=1, markdown="Page 1 text"))
        return expected_result

    mock_engine.process_document.side_effect = fake_process_doc

    coord = WorkerCoordinator(
        engine=mock_engine,
        settings=Settings(dpi=200),
        queue_manager=None,
    )

    # Enqueue work and termination sentinel
    coord.task_queue.put(doc_path)
    coord.task_queue.put(None)

    # Run loop directly in a worker thread
    worker_th = threading.Thread(target=coord.worker_loop, name="OCRWorkerThread", daemon=True)
    coord.worker_thread = worker_th
    worker_th.start()
    worker_th.join(timeout=3.0)

    assert not worker_th.is_alive()

    # Collect dispatched events
    events: List[WorkerEvent] = []
    while not coord.result_queue.empty():
        events.append(coord.result_queue.get_nowait())

    assert len(events) == 3
    assert events[0].event_type == WorkerEventType.STARTED
    assert events[0].file_path == str(doc_path)
    assert events[0].processed_dpi == 200

    assert events[1].event_type == WorkerEventType.PAGE_PROGRESS
    assert events[1].current_page == 1
    assert events[1].total_pages == 1

    assert events[2].event_type == WorkerEventType.COMPLETED
    assert events[2].result is expected_result


def test_coordinator_worker_loop_handles_exception(tmp_path: Path) -> None:
    """Worker loop traps engine exceptions and enqueues FAILED WorkerEvent."""
    doc_path = tmp_path / "bad.pdf"
    doc_path.write_bytes(b"%PDF-bad")

    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = RuntimeError("Engine connection refused")

    coord = WorkerCoordinator(
        engine=mock_engine,
        settings=Settings(),
        queue_manager=None,
    )

    coord.task_queue.put(doc_path)
    coord.task_queue.put(None)

    worker_th = threading.Thread(target=coord.worker_loop, name="OCRWorkerThread", daemon=True)
    coord.worker_thread = worker_th
    worker_th.start()
    worker_th.join(timeout=3.0)

    events: List[WorkerEvent] = []
    while not coord.result_queue.empty():
        events.append(coord.result_queue.get_nowait())

    assert len(events) == 2
    assert events[0].event_type == WorkerEventType.STARTED
    assert events[1].event_type == WorkerEventType.FAILED
    assert "Engine connection refused" in (events[1].error or "")


def test_coordinator_worker_loop_handles_cancelled_result(tmp_path: Path) -> None:
    """Worker loop detects cancelled result status and enqueues CANCELLED WorkerEvent."""
    doc_path = tmp_path / "cancelled.pdf"
    doc_path.write_bytes(b"%PDF-cancelled")

    mock_engine = MagicMock()
    cancelled_result = OCRResult(
        file_path=doc_path,
        status=JobStatus.CANCELLED,
        error="Aborted by user token",
        cancelled=True,
    )
    mock_engine.process_document.return_value = cancelled_result

    coord = WorkerCoordinator(
        engine=mock_engine,
        settings=Settings(),
        queue_manager=None,
    )

    coord.task_queue.put(doc_path)
    coord.task_queue.put(None)

    worker_th = threading.Thread(target=coord.worker_loop, name="OCRWorkerThread", daemon=True)
    coord.worker_thread = worker_th
    worker_th.start()
    worker_th.join(timeout=3.0)

    events: List[WorkerEvent] = []
    while not coord.result_queue.empty():
        events.append(coord.result_queue.get_nowait())

    assert len(events) == 2
    assert events[0].event_type == WorkerEventType.STARTED
    assert events[1].event_type == WorkerEventType.CANCELLED
    assert "Aborted by user token" in (events[1].error or "")


def test_coordinator_shutdown_drains_tasks_and_cancels_timer() -> None:
    """shutdown() cancels after timer, purges unstarted tasks, enqueues sentinel, joins thread."""
    cancelled_timers: List[str] = []

    def fake_after(ms: int, cb: Any) -> str:
        return "timer#active"

    def fake_after_cancel(timer_id: str) -> None:
        cancelled_timers.append(timer_id)

    shutdown_evt = threading.Event()
    coord = WorkerCoordinator(
        engine=None,
        settings=Settings(),
        queue_manager=None,
        after=fake_after,
        after_cancel=fake_after_cancel,
        shutdown_event=shutdown_evt,
    )
    coord.start()

    # Enqueue multiple unstarted tasks
    coord.task_queue.put(Path("pending1.pdf"))
    coord.task_queue.put(Path("pending2.pdf"))

    assert coord.poll_id == "timer#active"

    coord.shutdown(timeout=2.0)

    assert cancelled_timers == ["timer#active"]
    assert coord.poll_id is None
    assert coord.task_queue.empty()
    assert coord.worker_thread is not None
    assert not coord.worker_thread.is_alive()
