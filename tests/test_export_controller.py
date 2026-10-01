"""Isolated unit tests for gui/export_controller.py.

Tests ExportController single and batch exports, transient text preservation,
concurrency locks, and error handling using lightweight duck-typed fake controls.
Runs 100% headless without requiring ctk.CTk or a display server.
"""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from core.engine import JobStatus, OCRResult, PageResult
from core.models import OutputFormat
from gui.export_controller import ExportController
from gui.queue_manager import QueueItem, QueueItemStatus
from gui.theme import (
    COLOR_ACCENT_PRIMARY,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_SURFACE_BORDER,
    COLOR_TEXT_SUBTLE,
)


class FakeButton:
    """Duck-typed button widget fake tracking cget and configure calls."""

    def __init__(self, text: str = "", state: str = "disabled", **kwargs: Any) -> None:
        self.attrs: Dict[str, Any] = {
            "text": text,
            "state": state,
            "fg_color": COLOR_INTERACTIVE_NEUTRAL,
            "text_color": COLOR_TEXT_SUBTLE,
            "border_width": 1,
            "border_color": COLOR_SURFACE_BORDER,
        }
        self.attrs.update(kwargs)

    def cget(self, key: str) -> Any:
        return self.attrs.get(key)

    def configure(self, **kwargs: Any) -> None:
        self.attrs.update(kwargs)


class FakeOptionMenu:
    """Duck-typed option menu widget fake tracking value selection."""

    def __init__(self, value: str = "Markdown & JSON (.md + .json)") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class StubQueueManager:
    """Lightweight in-memory queue manager stub for controller testing."""

    def __init__(self) -> None:
        self.items: Dict[str, QueueItem] = {}
        self.selected_item_id: Optional[str] = None


@pytest.fixture
def export_harness():
    """Build an ExportController instance wired with test doubles."""
    qm = StubQueueManager()
    btn_sel = FakeButton(text="Export Selected")
    btn_all = FakeButton(text="Export All")
    opt_fmt = FakeOptionMenu()

    footer_messages: List[Optional[str]] = []
    after_calls: List[tuple] = []
    safe_after_callbacks: List[tuple] = []
    drained_callbacks: List[Any] = []
    ui_updates = {"count": 0}
    is_shutdown = [False]
    shutdown_ev = threading.Event()

    def fake_update_footer(msg: Optional[str] = None) -> None:
        footer_messages.append(msg)

    def fake_after(ms: int, func: Any, *args: Any) -> Any:
        after_calls.append((ms, func, args))
        return f"after_{len(after_calls)}"

    def fake_safe_after(ms: int, func: Any, *args: Any) -> None:
        safe_after_callbacks.append((func, args))

    def fake_drain() -> None:
        while safe_after_callbacks:
            fn, args = safe_after_callbacks.pop(0)
            drained_callbacks.append(fn)
            fn(*args)

    def fake_update_ui() -> None:
        ui_updates["count"] += 1

    ctrl = ExportController(
        queue_manager=qm,
        safe_after=fake_safe_after,
        after=fake_after,
        update_footer=fake_update_footer,
        is_shutting_down=lambda: is_shutdown[0],
        shutdown_event=shutdown_ev,
        drain_ui_callbacks=fake_drain,
        update_ui=fake_update_ui,
        btn_export_selected=btn_sel,
        btn_export_all=btn_all,
        opt_export_format=opt_fmt,
        format_error=lambda e: f"Friendly: {e}",
    )

    return {
        "ctrl": ctrl,
        "qm": qm,
        "btn_sel": btn_sel,
        "btn_all": btn_all,
        "opt_fmt": opt_fmt,
        "footer_messages": footer_messages,
        "after_calls": after_calls,
        "safe_after_callbacks": safe_after_callbacks,
        "drained_callbacks": drained_callbacks,
        "ui_updates": ui_updates,
        "is_shutdown": is_shutdown,
        "shutdown_ev": shutdown_ev,
        "drain_all": fake_drain,
    }


def test_export_controller_default_state(export_harness):
    """Verify initial property state and format mapping."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]

    assert ctrl.is_exporting is False
    assert ctrl.export_thread is None
    assert ctrl.get_selected_export_format() == OutputFormat.BOTH


def test_export_controller_format_switching(export_harness):
    """Verify option menu format strings resolve to correct OutputFormat enum."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    opt_fmt: FakeOptionMenu = h["opt_fmt"]

    opt_fmt.set("Word Document (.docx)")
    assert ctrl.get_selected_export_format() == OutputFormat.DOCX

    opt_fmt.set("Markdown & JSON (.md + .json)")
    assert ctrl.get_selected_export_format() == OutputFormat.BOTH

    opt_fmt.set("Unknown Format")
    assert ctrl.get_selected_export_format() == OutputFormat.BOTH


def test_update_buttons_disabled_and_enabled_states(export_harness):
    """Verify button enabled state and styling transitions based on queue completion."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    btn_sel: FakeButton = h["btn_sel"]
    btn_all: FakeButton = h["btn_all"]

    # 1. Nothing completed
    ctrl.update_buttons(selected_completed=False, completed_count=0)
    assert btn_sel.cget("state") == "disabled"
    assert btn_sel.cget("text") == "Export Selected"
    assert btn_all.cget("state") == "disabled"
    assert btn_all.cget("text") == "Export All"

    # 2. Selected item completed, batch has 1 item
    ctrl.update_buttons(selected_completed=True, completed_count=1)
    assert btn_sel.cget("state") == "normal"
    assert btn_sel.cget("fg_color") == COLOR_ACCENT_PRIMARY
    assert btn_all.cget("state") == "normal"


def test_update_buttons_preserves_transient_exported_text(export_harness):
    """Verify transient 'Exported!' and 'Exported All!' messages are not overwritten during flush."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    btn_sel: FakeButton = h["btn_sel"]
    btn_all: FakeButton = h["btn_all"]

    btn_sel.configure(text="Exported!")
    btn_all.configure(text="Exported All!")

    ctrl.update_buttons(selected_completed=True, completed_count=2)
    assert btn_sel.cget("text") == "Exported!"
    assert btn_all.cget("text") == "Exported All!"


def test_update_buttons_shows_exporting_when_active(export_harness):
    """Verify Export All reflects 'Exporting...' state while batch worker is running."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    btn_all: FakeButton = h["btn_all"]

    ctrl._is_exporting = True
    ctrl.update_buttons(selected_completed=False, completed_count=5)

    assert btn_all.cget("text") == "Exporting..."
    assert btn_all.cget("state") == "disabled"


def test_on_export_selected_no_selection_noop(export_harness):
    """Verify on_export_selected does nothing when no item is selected."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    mock_ask = MagicMock()
    ctrl.ask_directory = mock_ask

    ctrl.on_export_selected()
    mock_ask.assert_not_called()


def test_on_export_selected_dialog_cancelled(export_harness, tmp_path: Path):
    """Verify cancelling directory picker exits without calling save_artifacts."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]

    f = tmp_path / "test.png"
    f.write_bytes(b"data")
    item = QueueItem(item_id="item_1", file_path=f, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f), status=JobStatus.SUCCESS))
    qm.items["item_1"] = item
    qm.selected_item_id = "item_1"

    ctrl.ask_directory = lambda **kw: ""
    mock_save = MagicMock()
    ctrl.save_artifacts = mock_save

    ctrl.on_export_selected()
    mock_save.assert_not_called()


def test_on_export_selected_success(export_harness, tmp_path: Path):
    """Verify on_export_selected calls save_artifacts, updates footer, and sets transient text."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]
    btn_sel: FakeButton = h["btn_sel"]

    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF")
    res = OCRResult(file_path=str(f), status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="# Doc")])
    item = QueueItem(item_id="doc_id", file_path=f, status=QueueItemStatus.SUCCESS, result=res)
    qm.items["doc_id"] = item
    qm.selected_item_id = "doc_id"

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    ctrl.ask_directory = lambda **kw: str(out_dir)

    mock_save = MagicMock(return_value=[out_dir / "doc.md"])
    ctrl.save_artifacts = mock_save

    ctrl.on_export_selected()

    mock_save.assert_called_once()
    assert btn_sel.cget("text") == "Exported!"
    assert any("Exported 1 files" in msg for msg in h["footer_messages"] if msg)
    assert len(h["after_calls"]) == 1
    assert h["after_calls"][0][0] == 1200


def test_on_export_selected_error_handling(export_harness, tmp_path: Path):
    """Verify single-document export error updates footer with formatted message."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]

    f = tmp_path / "err_doc.pdf"
    f.write_bytes(b"%PDF")
    item = QueueItem(item_id="err_id", file_path=f, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f), status=JobStatus.SUCCESS))
    qm.items["err_id"] = item
    qm.selected_item_id = "err_id"

    ctrl.ask_directory = lambda **kw: str(tmp_path)
    ctrl.save_artifacts = MagicMock(side_effect=IOError("Disk full"))

    ctrl.on_export_selected()

    assert any("Friendly: Disk full" in msg for msg in h["footer_messages"] if msg)


def test_on_export_all_empty_queue_returns_none(export_harness):
    """Verify on_export_all returns None when queue has no completed items."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    mock_ask = MagicMock()
    ctrl.ask_directory = mock_ask

    result = ctrl.on_export_all()
    assert result is None
    mock_ask.assert_not_called()


def test_on_export_all_sync_success(export_harness, tmp_path: Path):
    """Verify on_export_all executes synchronously when sync=True and exports all items."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]
    btn_all: FakeButton = h["btn_all"]

    f1 = tmp_path / "doc1.pdf"
    f2 = tmp_path / "doc2.pdf"
    f1.write_bytes(b"1")
    f2.write_bytes(b"2")

    res1 = OCRResult(file_path=str(f1), status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="1")])
    res2 = OCRResult(file_path=str(f2), status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="2")])
    qm.items["id1"] = QueueItem(item_id="id1", file_path=f1, status=QueueItemStatus.SUCCESS, result=res1)
    qm.items["id2"] = QueueItem(item_id="id2", file_path=f2, status=QueueItemStatus.SUCCESS, result=res2)

    out_dir = tmp_path / "batch_out"
    out_dir.mkdir()
    ctrl.ask_directory = lambda **kw: str(out_dir)

    mock_save = MagicMock(return_value=[out_dir / "out.md"])
    ctrl.save_artifacts = mock_save

    thread = ctrl.on_export_all(sync=True)
    assert thread is None
    h["drain_all"]()

    assert mock_save.call_count == 2
    assert btn_all.cget("text") == "Exported All!"
    assert any("Exported 2 documents" in msg for msg in h["footer_messages"] if msg)
    assert ctrl.is_exporting is False


def test_on_export_all_concurrency_lock(export_harness, tmp_path: Path):
    """Verify concurrent on_export_all requests are rejected when export is active."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]

    f = tmp_path / "doc.pdf"
    f.write_bytes(b"data")
    qm.items["id"] = QueueItem(item_id="id", file_path=f, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f), status=JobStatus.SUCCESS))

    ctrl._is_exporting = True
    assert ctrl.on_export_all() is None


def test_on_export_all_async_thread_and_wait(export_harness, tmp_path: Path):
    """Verify on_export_all spawns background thread and wait_for_export synchronizes."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]

    f = tmp_path / "async_doc.pdf"
    f.write_bytes(b"data")
    qm.items["id"] = QueueItem(item_id="id", file_path=f, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f), status=JobStatus.SUCCESS))

    out_dir = tmp_path / "async_out"
    out_dir.mkdir()
    ctrl.ask_directory = lambda **kw: str(out_dir)
    ctrl.save_artifacts = MagicMock(return_value=[out_dir / "async_doc.md"])

    thread = ctrl.on_export_all(sync=False)
    assert thread is not None
    assert isinstance(thread, threading.Thread)
    assert thread.daemon is True

    ctrl.wait_for_export(timeout=5.0)

    assert not thread.is_alive()
    assert ctrl.is_exporting is False
    assert h["ui_updates"]["count"] >= 1


def test_on_export_all_partial_failure_continues(export_harness, tmp_path: Path):
    """Verify single file failure during batch export does not abort the remaining items."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]

    f1 = tmp_path / "fail.pdf"
    f2 = tmp_path / "succeed.pdf"
    f1.write_bytes(b"fail")
    f2.write_bytes(b"succeed")

    qm.items["id1"] = QueueItem(item_id="id1", file_path=f1, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f1), status=JobStatus.SUCCESS))
    qm.items["id2"] = QueueItem(item_id="id2", file_path=f2, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f2), status=JobStatus.SUCCESS))

    out_dir = tmp_path / "fail_out"
    out_dir.mkdir()
    ctrl.ask_directory = lambda **kw: str(out_dir)

    def side_effect(res, *args, **kwargs):
        if "fail.pdf" in res.file_path:
            raise PermissionError("Access denied")
        return [out_dir / "succeed.md"]

    ctrl.save_artifacts = MagicMock(side_effect=side_effect)

    ctrl.on_export_all(sync=True)
    h["drain_all"]()

    assert ctrl.save_artifacts.call_count == 2
    assert any("1/2 succeeded" in msg and "1 failed" in msg for msg in h["footer_messages"] if msg)


def test_on_export_all_shutdown_aborts_early(export_harness, tmp_path: Path):
    """Verify batch loop aborts immediately when shutdown is signaled."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    qm: StubQueueManager = h["qm"]

    f1 = tmp_path / "doc1.pdf"
    f2 = tmp_path / "doc2.pdf"
    f1.write_bytes(b"1")
    f2.write_bytes(b"2")

    qm.items["id1"] = QueueItem(item_id="id1", file_path=f1, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f1), status=JobStatus.SUCCESS))
    qm.items["id2"] = QueueItem(item_id="id2", file_path=f2, status=QueueItemStatus.SUCCESS, result=OCRResult(file_path=str(f2), status=JobStatus.SUCCESS))

    ctrl.ask_directory = lambda **kw: str(tmp_path)
    ctrl.save_artifacts = MagicMock(return_value=[tmp_path / "doc.md"])

    # Signal shutdown before running
    h["is_shutdown"][0] = True
    ctrl.on_export_all(sync=True)

    # Aborted before processing any document
    ctrl.save_artifacts.assert_not_called()


def test_reset_buttons_guarded_by_shutdown(export_harness):
    """Verify reset button methods are no-ops when application is shutting down."""
    h = export_harness
    ctrl: ExportController = h["ctrl"]
    btn_sel: FakeButton = h["btn_sel"]
    btn_all: FakeButton = h["btn_all"]

    btn_sel.configure(text="Exported!")
    btn_all.configure(text="Exported All!")

    h["is_shutdown"][0] = True
    ctrl.reset_export_selected_button()
    ctrl.reset_export_all_button()

    # Did NOT reset because shutdown guard was active
    assert btn_sel.cget("text") == "Exported!"
    assert btn_all.cget("text") == "Exported All!"

    h["is_shutdown"][0] = False
    ctrl.reset_export_selected_button()
    ctrl.reset_export_all_button()

    # Now reset
    assert btn_sel.cget("text") == "Export Selected"
    assert btn_all.cget("text") == "Export All"
