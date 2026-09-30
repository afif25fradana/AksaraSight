"""Isolated unit tests for gui/queue_manager.py.

Tests QueueManager public behavior using lightweight fakes and a headless
CustomTkinter root, independent of the complete OCRApp monolith.
"""

from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import customtkinter as ctk
import pytest

from core.engine import JobStatus, OCRResult, PageResult
from gui.queue_manager import (
    QueueItem,
    QueueItemStatus,
    QueueManager,
    _format_file_size,
)
from gui.theme import (
    COLOR_ACCENT_PRIMARY,
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_ROW_SELECTED_BG,
)


@pytest.fixture(scope="module")
def app_root():
    """Create a headless CTk root window for the test module."""
    root = ctk.CTk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def qm_harness(app_root):
    """Instantiate a QueueManager with dedicated real widgets and mock callbacks."""
    scroll = ctk.CTkScrollableFrame(app_root)
    scroll.pack()
    empty_lbl = ctk.CTkLabel(app_root, text="Drop files here")
    empty_lbl.pack()

    # Container frame using grid for header labels (matches OCRApp layout)
    header_container = ctk.CTkFrame(app_root)
    header_container.pack()
    title_lbl = ctk.CTkLabel(header_container, text="Queue (0)")
    title_lbl.grid(row=0, column=0)
    hint_lbl = ctk.CTkLabel(header_container, text="Cleanup hint")

    task_q: queue.Queue = queue.Queue()
    footer_messages: list[str | None] = []

    on_selection_changed = MagicMock()
    on_queue_emptied = MagicMock()
    on_queue_changed = MagicMock()

    scheduled_afters = []
    ui_callback_queue = []

    def mock_after(ms, fn, *args):
        scheduled_afters.append((fn, args))
        return "after_id"

    def mock_safe_after(ms, fn, *args):
        ui_callback_queue.append((fn, args))
        return "safe_after_id"

    def drain_ui_callbacks():
        while ui_callback_queue:
            fn, args = ui_callback_queue.pop(0)
            fn(*args)

    dpi_holder = [100]
    shutting_down = [False]

    manager = QueueManager(
        queue_scroll=scroll,
        empty_queue_label=empty_lbl,
        queue_title=title_lbl,
        queue_cleanup_hint=hint_lbl,
        task_queue=task_q,
        safe_after=mock_safe_after,
        after=mock_after,
        update_footer=lambda msg=None: footer_messages.append(msg),
        get_current_dpi=lambda: dpi_holder[0],
        is_shutting_down=lambda: shutting_down[0],
        drain_ui_callbacks=drain_ui_callbacks,
        update_ui=lambda: None,
        on_selection_changed=on_selection_changed,
        on_queue_emptied=on_queue_emptied,
        on_queue_changed=on_queue_changed,
    )

    yield SimpleNamespace(
        manager=manager,
        scroll=scroll,
        empty_lbl=empty_lbl,
        header_container=header_container,
        title_lbl=title_lbl,
        hint_lbl=hint_lbl,
        task_q=task_q,
        footer_messages=footer_messages,
        on_selection_changed=on_selection_changed,
        on_queue_emptied=on_queue_emptied,
        on_queue_changed=on_queue_changed,
        scheduled_afters=scheduled_afters,
        ui_callback_queue=ui_callback_queue,
        drain_ui_callbacks=drain_ui_callbacks,
        dpi_holder=dpi_holder,
        shutting_down=shutting_down,
    )

    # Clean up created rows
    for item in list(manager.items.values()):
        if item.row_frame:
            try:
                item.row_frame.destroy()
            except Exception:
                pass
    try:
        scroll.destroy()
        empty_lbl.destroy()
        header_container.destroy()
    except Exception:
        pass


def test_format_file_size_utility():
    """Verify byte formatting converts correctly to B, KB, and MB strings."""
    assert _format_file_size(0) == "0 B"
    assert _format_file_size(500) == "500 B"
    assert _format_file_size(1024) == "1.0 KB"
    assert _format_file_size(1536) == "1.5 KB"
    assert _format_file_size(1024 * 1024) == "1.0 MB"
    assert _format_file_size(5 * 1024 * 1024) == "5.0 MB"


def test_queue_manager_initial_state_and_property_setters(qm_harness):
    """Verify initial properties and property setters on QueueManager."""
    manager = qm_harness.manager
    assert manager.items == {}
    assert manager.selected_item_id is None
    assert manager.total_count == 0
    assert manager.pending_batch_inserts == 0
    assert manager.ingest_threads == []

    manager.selected_item_id = "test_id"
    assert manager.selected_item_id == "test_id"

    manager.total_count = 42
    assert manager.total_count == 42

    manager.pending_batch_inserts = 5
    assert manager.pending_batch_inserts == 5


def test_enqueue_single_file_item_validation(qm_harness, tmp_path: Path):
    """Verify non-files and unsupported extensions are rejected."""
    qm = qm_harness.manager
    # Non-existent file
    assert qm.enqueue_single_file_item(tmp_path / "nonexistent.pdf") is None

    # Unsupported extension
    unsupported = tmp_path / "doc.txt"
    unsupported.write_bytes(b"data")
    assert qm.enqueue_single_file_item(unsupported) is None
    assert len(qm.items) == 0
    assert qm.total_count == 0


def test_enqueue_single_file_item_success(qm_harness, tmp_path: Path):
    """Verify valid supported file is tracked, enqueued, and row widget created."""
    qm = qm_harness.manager
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy content")

    item = qm.enqueue_single_file_item(pdf_file)

    assert item is not None
    assert item.item_id == str(pdf_file)
    assert item.status == QueueItemStatus.QUEUED
    assert item.file_size_str is not None
    assert len(qm.items) == 1
    assert qm.total_count == 1
    assert qm_harness.task_q.get() == pdf_file

    # Real UI widget structure verified
    assert item.row_frame is not None
    assert item.chip_label is not None
    assert item.chip_label.cget("text") == "PDF"
    assert item.name_label.cget("text") == "sample.pdf"
    assert item.badge_label.cget("text") == "●"


def test_enqueue_single_file_item_duplicate_guard(qm_harness, tmp_path: Path):
    """Verify duplicate enqueue of QUEUED or PROCESSING item is rejected."""
    qm = qm_harness.manager
    f = tmp_path / "doc.png"
    f.write_bytes(b"img")

    item1 = qm.enqueue_single_file_item(f)
    assert item1 is not None

    # Duplicate while QUEUED rejected
    assert qm.enqueue_single_file_item(f) is None
    assert qm.total_count == 1

    # Duplicate while PROCESSING rejected
    item1.status = QueueItemStatus.PROCESSING
    assert qm.enqueue_single_file_item(f) is None

    # Re-enqueue allowed when previously completed or failed
    item1.status = QueueItemStatus.SUCCESS
    item2 = qm.enqueue_single_file_item(f)
    assert item2 is not None
    assert qm.total_count == 2


def test_enqueue_file_shutdown_guard(qm_harness, tmp_path: Path):
    """Verify enqueue_file returns None when is_shutting_down is True."""
    qm = qm_harness.manager
    qm_harness.shutting_down[0] = True
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF dummy")

    assert qm.enqueue_file(pdf) is None
    assert len(qm.items) == 0


def test_enqueue_file_single_file_updates_ui(qm_harness, tmp_path: Path):
    """Verify enqueue_file forgets empty label and updates header/footer."""
    qm = qm_harness.manager
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF dummy")

    assert qm_harness.empty_lbl.winfo_manager() == "pack"
    thread = qm.enqueue_file(pdf)

    assert thread is None
    assert qm_harness.empty_lbl.winfo_manager() == ""
    assert qm_harness.title_lbl.cget("text") == "Queue (1)"
    assert len(qm_harness.footer_messages) >= 1


def test_enqueue_file_directory_sync_empty(qm_harness, tmp_path: Path):
    """Verify sync enqueue on empty directory warns in footer and returns None."""
    qm = qm_harness.manager
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    res = qm.enqueue_file(empty_dir, sync=True)

    assert res is None
    assert any("No supported documents in empty_dir" in str(m) for m in qm_harness.footer_messages)
    assert len(qm.items) == 0


def test_enqueue_file_directory_sync_success(qm_harness, tmp_path: Path):
    """Verify sync directory scan enqueues all supported child files recursively."""
    qm = qm_harness.manager
    drop_dir = tmp_path / "docs"
    drop_dir.mkdir()
    sub_dir = drop_dir / "nested"
    sub_dir.mkdir()

    (drop_dir / "a.pdf").write_bytes(b"%PDF")
    (sub_dir / "b.png").write_bytes(b"PNG")
    (drop_dir / "c.txt").write_bytes(b"TXT")  # unsupported

    res = qm.enqueue_file(drop_dir, sync=True)

    assert res is None
    assert len(qm.items) == 2
    assert qm.total_count == 2
    assert qm_harness.empty_lbl.winfo_manager() == ""
    assert qm_harness.title_lbl.cget("text") == "Queue (2)"
    assert any("Enqueued 2 files from docs" in str(m) for m in qm_harness.footer_messages)


def test_enqueue_file_directory_async_spawns_thread_and_wait_for_ingest(qm_harness, tmp_path: Path):
    """Verify async directory enqueue returns background thread and wait_for_ingest drains."""
    qm = qm_harness.manager
    drop_dir = tmp_path / "async_docs"
    drop_dir.mkdir()
    (drop_dir / "doc.pdf").write_bytes(b"%PDF")

    thread = qm.enqueue_file(drop_dir, sync=False)

    assert thread is not None
    assert thread.name.startswith("FolderScan-")
    assert thread in qm.ingest_threads
    thread.join(timeout=2.0)
    assert qm.pending_batch_inserts >= 1

    # Drain via wait_for_ingest
    qm.wait_for_ingest(timeout=1.0)
    assert len(qm.items) == 1
    assert qm.pending_batch_inserts == 0


def test_enqueue_file_directory_scan_exception_handled(qm_harness, tmp_path: Path):
    """Verify directory scan exception logs warning and gracefully reports empty."""
    qm = qm_harness.manager
    drop_dir = tmp_path / "err_docs"
    drop_dir.mkdir()

    with patch.object(Path, "rglob", side_effect=OSError("Permission denied")):
        thread = qm.enqueue_file(drop_dir, sync=False)
        assert thread is not None
        thread.join(timeout=2.0)

    qm_harness.drain_ui_callbacks()
    assert any("No supported documents in err_docs" in str(m) for m in qm_harness.footer_messages)


def test_batch_insert_items_chunking(qm_harness, tmp_path: Path):
    """Verify batch_insert_items slices chunks and schedules remainder via after."""
    qm = qm_harness.manager
    files = [tmp_path / f"file_{i}.pdf" for i in range(5)]
    for f in files:
        f.write_bytes(b"%PDF")

    qm.pending_batch_inserts = 1

    # Run with chunk_size = 2
    qm.batch_insert_items(files, "test_folder", start_idx=0, chunk_size=2)

    # 2 files enqueued in first chunk
    assert len(qm.items) == 2
    assert len(qm_harness.scheduled_afters) == 1
    fn, args = qm_harness.scheduled_afters[0]
    assert fn == qm.batch_insert_items
    assert args == (files, "test_folder", 2, 2)


def test_batch_insert_items_shutdown_guard(qm_harness, tmp_path: Path):
    """Verify batch_insert_items aborts early when is_shutting_down is True."""
    qm = qm_harness.manager
    qm_harness.shutting_down[0] = True
    files = [tmp_path / "file.pdf"]
    files[0].write_bytes(b"%PDF")

    qm.pending_batch_inserts = 1
    qm.batch_insert_items(files, "folder", 0, 25)

    assert len(qm.items) == 0
    assert qm.pending_batch_inserts == 0
    assert len(qm_harness.scheduled_afters) == 0


def test_selection_lifecycle(qm_harness, tmp_path: Path):
    """Verify row selection highlighting and callback dispatching."""
    qm = qm_harness.manager
    f1 = tmp_path / "one.pdf"
    f2 = tmp_path / "two.pdf"
    f1.write_bytes(b"%PDF")
    f2.write_bytes(b"%PDF")

    item1 = qm.enqueue_single_file_item(f1)
    item2 = qm.enqueue_single_file_item(f2)

    # Auto-selected item1 on first enqueue
    assert qm.selected_item_id == item1.item_id
    qm_harness.on_selection_changed.assert_called_with(item1, True)

    # Re-select same item -> selection_changed is False
    qm.select_item(item1.item_id)
    qm_harness.on_selection_changed.assert_called_with(item1, False)

    # Switch selection to item 2
    qm.select_item(item2.item_id)
    assert qm.selected_item_id == item2.item_id
    assert item1.row_frame.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL
    assert item2.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG
    assert item2.indicator_bar.cget("fg_color") == COLOR_ACCENT_PRIMARY
    qm_harness.on_selection_changed.assert_called_with(item2, True)

    # Select non-existent item is ignored
    qm.select_item("unknown_id")
    assert qm.selected_item_id == item2.item_id


def test_clear_finished_behavior(qm_harness, tmp_path: Path):
    """Verify completed/failed items are removed, row widgets destroyed, and remaining selected."""
    qm = qm_harness.manager
    f1 = tmp_path / "1.pdf"
    f2 = tmp_path / "2.pdf"
    f3 = tmp_path / "3.pdf"
    f4 = tmp_path / "4.pdf"
    for f in (f1, f2, f3, f4):
        f.write_bytes(b"%PDF")

    i_success = qm.enqueue_single_file_item(f1)
    i_processing = qm.enqueue_single_file_item(f2)
    i_failed = qm.enqueue_single_file_item(f3)
    i_queued = qm.enqueue_single_file_item(f4)

    i_success.status = QueueItemStatus.SUCCESS
    i_processing.status = QueueItemStatus.PROCESSING
    i_failed.status = QueueItemStatus.FAILED
    i_queued.status = QueueItemStatus.QUEUED

    qm.select_item(i_success.item_id)  # Select finished item

    qm.clear_finished()

    # Finished items removed from manager
    assert set(qm.items.keys()) == {i_processing.item_id, i_queued.item_id}
    # Selection moved to first remaining item (processing)
    assert qm.selected_item_id == i_processing.item_id
    qm_harness.on_queue_changed.assert_called_once()


def test_clear_finished_all_empties_queue(qm_harness, tmp_path: Path):
    """Verify clearing all finished items triggers on_queue_emptied."""
    qm = qm_harness.manager
    f1 = tmp_path / "1.pdf"
    f1.write_bytes(b"%PDF")
    item = qm.enqueue_single_file_item(f1)
    item.status = QueueItemStatus.SUCCESS

    qm.clear_finished()

    assert len(qm.items) == 0
    assert qm.selected_item_id is None
    qm_harness.on_queue_emptied.assert_called_once()


def test_clear_finished_noop_when_no_finished_items(qm_harness, tmp_path: Path):
    """Verify clear_finished returns early when no finished items exist."""
    qm = qm_harness.manager
    f = tmp_path / "1.pdf"
    f.write_bytes(b"%PDF")
    qm.enqueue_single_file_item(f)

    qm.clear_finished()

    assert len(qm.items) == 1
    qm_harness.on_queue_changed.assert_not_called()
    qm_harness.on_queue_emptied.assert_not_called()


def test_update_header_cleanup_hint_threshold(qm_harness, tmp_path: Path):
    """Verify cleanup hint appears only when finished count exceeds 100."""
    qm = qm_harness.manager

    # 10 items finished: hint hidden
    for i in range(10):
        p = tmp_path / f"{i}.pdf"
        p.write_bytes(b"%PDF")
        item = qm.enqueue_single_file_item(p)
        item.status = QueueItemStatus.SUCCESS

    qm.update_header()
    assert qm_harness.hint_lbl.winfo_manager() == ""

    # Mock 101 finished items
    for i in range(10, 102):
        qm.items[str(i)] = QueueItem(item_id=str(i), file_path=tmp_path / f"{i}.pdf", status=QueueItemStatus.SUCCESS)

    qm.update_header()
    assert qm_harness.hint_lbl.winfo_manager() == "grid"
    assert "102 finished items" in qm_harness.hint_lbl.cget("text")


def test_format_item_meta_states(qm_harness, tmp_path: Path):
    """Verify metadata formatting strings across all QueueItemStatus states."""
    qm = qm_harness.manager
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF")

    # QUEUED
    item = QueueItem(item_id="1", file_path=p, status=QueueItemStatus.QUEUED, file_size_str="1.2 MB")
    assert qm.format_item_meta(item) == "PDF · 1.2 MB"

    # PROCESSING
    item.status = QueueItemStatus.PROCESSING
    assert qm.format_item_meta(item) == "PDF · 1.2 MB · Processing..."

    # FAILED
    item.status = QueueItemStatus.FAILED
    assert qm.format_item_meta(item) == "PDF · 1.2 MB · Failed"

    # CANCELLED without pages
    item.status = QueueItemStatus.CANCELLED
    item.result = None
    assert qm.format_item_meta(item) == "PDF · 1.2 MB · Cancelled"

    # CANCELLED with 1 page and DPI staleness
    item.result = OCRResult(file_path="1", status=JobStatus.CANCELLED, pages=[PageResult(page_num=1)])
    item.processed_dpi = 150  # current mocked to 100
    meta_canc = qm.format_item_meta(item)
    assert "PDF · 1.2 MB · Cancelled (1 page)" in meta_canc
    assert "· ⚠ processed @150 DPI" in meta_canc

    # SUCCESS 1 page
    item.status = QueueItemStatus.SUCCESS
    item.duration = 2.45
    item.result = OCRResult(file_path="1", status=JobStatus.SUCCESS, pages=[PageResult(page_num=1)])
    item.processed_dpi = 100  # matches current DPI
    assert qm.format_item_meta(item) == "PDF · 1.2 MB · 1 page · 2.5s"

    # SUCCESS multi-page truncated
    item.result = OCRResult(
        file_path="1",
        status=JobStatus.SUCCESS,
        pages=[PageResult(page_num=1), PageResult(page_num=2, truncated=True)],
    )
    assert qm.format_item_meta(item) == "PDF · 1.2 MB · 2 pages · 2.5s · ⚠ Truncated"

    # Dynamic file size computation if missing
    item.file_size_str = None
    assert "PDF · " in qm.format_item_meta(item)
    assert item.file_size_str is not None


def test_row_hover_styling(qm_harness, tmp_path: Path):
    """Verify hover enter and leave alter row background on unselected items only."""
    qm = qm_harness.manager
    f1 = tmp_path / "u.pdf"
    f2 = tmp_path / "s.pdf"
    f1.write_bytes(b"%PDF")
    f2.write_bytes(b"%PDF")

    item_u = qm.enqueue_single_file_item(f1)
    item_s = qm.enqueue_single_file_item(f2)
    qm.select_item(item_s.item_id)

    # Hover enter unselected -> HOVER color
    qm._on_row_enter(item_id=item_u.item_id)
    assert item_u.row_frame.cget("fg_color") == COLOR_INTERACTIVE_HOVER

    # Hover leave unselected -> NEUTRAL color
    qm._on_row_leave(item_id=item_u.item_id)
    assert item_u.row_frame.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL

    # Hover enter/leave selected -> keeps ROW_SELECTED_BG
    qm._on_row_enter(item_id=item_s.item_id)
    assert item_s.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG
    qm._on_row_leave(item_id=item_s.item_id)
    assert item_s.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG

    # Hover enter/leave resolved from child widget in event
    event = SimpleNamespace(widget=item_u.chip_label)
    qm._on_row_enter(event)
    assert item_u.row_frame.cget("fg_color") == COLOR_INTERACTIVE_HOVER
    qm._on_row_leave(event)
    assert item_u.row_frame.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL
