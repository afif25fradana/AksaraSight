import inspect
import json
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
import pytest
import customtkinter as ctk

from config.settings import Settings
from core.constants import SUPPORTED_EXTENSIONS
from core.formatter import save_artifacts
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat, PageResult
from gui.app import (
    COLOR_ACCENT_PRIMARY,
    COLOR_CANVAS_BG,
    COLOR_CHIP_IMG_BG,
    COLOR_CHIP_PDF_BG,
    COLOR_DRAGOVER_BG,
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_ROW_SELECTED_BG,
    COLOR_STATUS_CANCELLED,
    COLOR_SURFACE_1,
    COLOR_SURFACE_BORDER,
    COLOR_SURFACE_BORDER_HOVER,
    COLOR_TEXT_PRIMARY,
    OCRApp,
    QueueItem,
    QueueItemStatus,
    WorkerEvent,
    WorkerEventType,
)


def test_worker_event_dataclass():
    """Verify WorkerEvent dataclass creation and attributes."""
    event = WorkerEvent(
        event_type=WorkerEventType.STARTED,
        file_path="sample.png",
    )
    assert event.event_type == WorkerEventType.STARTED
    assert event.file_path == "sample.png"
    assert event.result is None
    assert event.error is None


def test_app_initialization_and_clean_shutdown():
    """Verify OCRApp starts background worker and shuts down cleanly."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()  # Headless execution

    try:
        assert app.title() == "GLM-OCR Local Studio"
        assert app._worker_thread.is_alive()
        assert not app._is_shutting_down
        assert not app._shutdown_event.is_set()
        assert app._status_label is app._footer_status
    finally:
        app._on_closing()

    assert app._is_shutting_down
    assert app._shutdown_event.is_set()
    assert mock_engine.close.call_count == 1
    # Worker thread should terminate
    app._worker_thread.join(timeout=1.0)
    assert not app._worker_thread.is_alive()


def test_app_enqueue_and_worker_success(tmp_path):
    """Verify enqueuing a file dispatches to engine and emits STARTED and COMPLETED events."""
    mock_engine = MagicMock()
    test_file = tmp_path / "doc.pdf"
    test_file.write_bytes(b"dummy")

    fake_result = OCRResult(file_path=str(test_file), status=JobStatus.SUCCESS)
    mock_engine.process_document.return_value = fake_result

    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        app.enqueue_file(test_file)

        # Wait for worker thread to process item
        deadline = time.time() + 2.0
        while time.time() < deadline:
            app._process_result_queue()
            if mock_engine.process_document.call_count > 0 and app._status_label.cget("text").startswith("Done:"):
                break
            time.sleep(0.05)

        assert mock_engine.process_document.call_count == 1
        assert str(test_file) in mock_engine.process_document.call_args[0][0]
        assert "Done: doc.pdf (SUCCESS)" in app._status_label.cget("text")
    finally:
        app._on_closing()


def test_app_worker_processing_failure(tmp_path):
    """Verify failed OCRResult emits FAILED event and updates UI status label."""
    mock_engine = MagicMock()
    test_file = tmp_path / "corrupt.pdf"
    test_file.write_bytes(b"bad data")

    fake_result = OCRResult(file_path=str(test_file), status=JobStatus.FAILED, error="Corrupt document")
    mock_engine.process_document.return_value = fake_result

    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        app.enqueue_file(test_file)

        deadline = time.time() + 2.0
        while time.time() < deadline:
            app._process_result_queue()
            if mock_engine.process_document.call_count > 0 and app._status_label.cget("text").startswith("Failed:"):
                break
            time.sleep(0.05)

        assert mock_engine.process_document.call_count == 1
        assert "Failed: corrupt.pdf - Corrupt document" in app._status_label.cget("text")
    finally:
        app._on_closing()


def test_app_worker_loop_fatal_crash():
    """Verify outermost try/except catches fatal loop crashes and emits WORKER_CRASHED event."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # Simulate fatal loop crash by sabotaging task_queue.get
        def crashing_get(timeout=None):
            raise SystemError("Simulated unhandled runtime catastrophe")

        app._task_queue.get = crashing_get

        deadline = time.time() + 2.0
        while time.time() < deadline:
            app._process_result_queue()
            if "Fatal Worker Error:" in app._status_label.cget("text"):
                break
            time.sleep(0.05)

        assert "Fatal Worker Error: Worker loop crashed: Simulated unhandled runtime catastrophe" in app._status_label.cget("text")
    finally:
        app._on_closing()


def test_app_dnd_drop_handling():
    """Verify _on_drop_files parses space-delimited and braced file lists correctly."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        drop_data = "{C:/Folder Name/invoice 1.pdf} C:/simple.png"
        event = SimpleNamespace(data=drop_data)

        with patch.object(app, "enqueue_file") as mock_enqueue:
            app._on_drop_files(event)

            assert mock_enqueue.call_count == 2
            assert mock_enqueue.call_args_list[0][0][0] == Path("C:/Folder Name/invoice 1.pdf")
            assert mock_enqueue.call_args_list[1][0][0] == Path("C:/simple.png")
    finally:
        app._on_closing()


def test_supported_extensions_filtering(tmp_path):
    """Verify unsupported extensions are filtered out and not enqueued."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        valid_file = tmp_path / "valid.pdf"
        valid_file.write_bytes(b"content")

        invalid_file = tmp_path / "unsupported.docx"
        invalid_file.write_bytes(b"content")

        app.enqueue_file(valid_file)
        app.enqueue_file(invalid_file)

        assert str(valid_file.resolve()) in app._queue_items
        assert str(invalid_file.resolve()) not in app._queue_items
        assert len(app._queue_items) == 1
    finally:
        app._on_closing()


def test_selection_race_condition(tmp_path):
    """Verify worker completion on a non-selected item updates item state but preserves current preview."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        file1 = tmp_path / "item1.pdf"
        file1.write_bytes(b"pdf1")
        file2 = tmp_path / "item2.png"
        file2.write_bytes(b"png2")

        app.enqueue_file(file1)
        app.enqueue_file(file2)

        file1_id = str(file1.resolve())
        file2_id = str(file2.resolve())

        # Select file 1 explicitly and switch to Text Preview
        app._select_queue_item(file1_id)
        assert app._selected_item_id == file1_id
        app.select_tab("Text Preview")

        # Verify preview pane currently reflects file 1
        initial_preview = app._tb_preview.get("1.0", "end")
        assert "item1.pdf" in initial_preview
        assert "item2.png" not in initial_preview

        # Simulate delayed worker completion event for file 2
        result2 = OCRResult(
            file_path=file2_id,
            status=JobStatus.SUCCESS,
            total_duration=1.5,
            pages=[PageResult(page_num=1, markdown="# Page 2 Extracted Heading", latency=1.5)],
        )
        event2 = WorkerEvent(
            event_type=WorkerEventType.COMPLETED,
            file_path=file2_id,
            result=result2,
        )

        app._handle_worker_event(event2)

        # Race-free check: active selection must STILL be file 1
        assert app._selected_item_id == file1_id

        # Preview pane must NOT have been overwritten by file 2
        preview_text_after_race = app._tb_preview.get("1.0", "end")
        assert "item1.pdf" in preview_text_after_race
        assert "Page 2 Extracted Heading" not in preview_text_after_race

        # Underlying queue item and row for file 2 MUST be updated
        item2 = app._queue_items[file2_id]
        assert item2.status == QueueItemStatus.SUCCESS
        assert item2.duration == 1.5
        assert item2.result is result2
        assert item2.badge_label.cget("text") == "●"
        assert "1.5s" in item2.detail_label.cget("text")

        # Now when user selects file 2, preview pane updates to file 2's content
        app._select_queue_item(file2_id)
        assert app._selected_item_id == file2_id
        assert "Page 2 Extracted Heading" in app._tb_preview.get("1.0", "end")
        app.select_tab("Raw Markdown")
        assert "Page 2 Extracted Heading" in app._tb_markdown.get("1.0", "end")
    finally:
        app._on_closing()


def test_preview_placeholders_for_unprocessed_items(tmp_path):
    """Verify distinct placeholder messages and button states for QUEUED, PROCESSING, and FAILED items."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        file1 = tmp_path / "sample.pdf"
        file1.write_bytes(b"content")

        app.enqueue_file(file1)
        file1_id = str(file1.resolve())
        item = app._queue_items[file1_id]

        # 1. QUEUED state
        app._select_queue_item(file1_id)
        assert "is queued for processing" in app._tb_markdown.get("1.0", "end")
        app.select_tab("Text Preview")
        assert "Document Queued: sample.pdf" in app._tb_preview.get("1.0", "end")
        app.select_tab("JSON Tree")
        assert '"status": "QUEUED"' in app._tb_json.get("1.0", "end")
        assert app._btn_copy.cget("state") == "disabled"
        assert app._btn_export_selected.cget("state") == "disabled"

        # 2. PROCESSING state
        item.status = QueueItemStatus.PROCESSING
        app.select_tab("Raw Markdown")
        assert "is currently being processed" in app._tb_markdown.get("1.0", "end")
        app.select_tab("Text Preview")
        assert "Processing Document: sample.pdf" in app._tb_preview.get("1.0", "end")
        app.select_tab("JSON Tree")
        assert '"status": "PROCESSING"' in app._tb_json.get("1.0", "end")
        assert app._btn_copy.cget("state") == "disabled"
        assert app._btn_export_selected.cget("state") == "disabled"
        assert app._btn_export_selected.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL

        # 3. FAILED state
        item.status = QueueItemStatus.FAILED
        item.error = "Connection timeout to local backend"
        app.select_tab("Raw Markdown")
        assert "Error processing sample.pdf" in app._tb_markdown.get("1.0", "end")
        app.select_tab("Text Preview")
        assert "Connection timeout to local backend" in app._tb_preview.get("1.0", "end")
        app.select_tab("JSON Tree")
        assert '"status": "FAILED"' in app._tb_json.get("1.0", "end")
        assert app._btn_copy.cget("state") == "disabled"
        assert app._btn_export_selected.cget("state") == "disabled"
    finally:
        app._on_closing()


def test_clear_finished_behavior(tmp_path):
    """Verify Clear Finished removes SUCCESS/FAILED items, preserves QUEUED/PROCESSING, and resets selection."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        f1 = tmp_path / "f1.pdf"
        f2 = tmp_path / "f2.pdf"
        f3 = tmp_path / "f3.pdf"
        f4 = tmp_path / "f4.pdf"
        for f in (f1, f2, f3, f4):
            f.write_bytes(b"data")
            app.enqueue_file(f)

        id1, id2, id3, id4 = str(f1.resolve()), str(f2.resolve()), str(f3.resolve()), str(f4.resolve())

        # Set diverse statuses:
        # id1 -> SUCCESS
        app._queue_items[id1].status = QueueItemStatus.SUCCESS
        app._queue_items[id1].result = OCRResult(file_path=id1, status=JobStatus.SUCCESS)
        # id2 -> PROCESSING
        app._queue_items[id2].status = QueueItemStatus.PROCESSING
        # id3 -> QUEUED
        app._queue_items[id3].status = QueueItemStatus.QUEUED
        # id4 -> FAILED
        app._queue_items[id4].status = QueueItemStatus.FAILED
        app._queue_items[id4].error = "Corrupt PDF"

        # Select id1 (completed item)
        app._select_queue_item(id1)
        assert app._selected_item_id == id1

        # Execute Clear Finished
        app._on_clear_finished()

        # Finished items (id1 and id4) must be removed
        assert id1 not in app._queue_items
        assert id4 not in app._queue_items

        # Unfinished items (id2 and id3) must remain
        assert id2 in app._queue_items
        assert id3 in app._queue_items
        assert len(app._queue_items) == 2

        # Active selection should shift to first remaining item (id2)
        assert app._selected_item_id == id2

        # Executing Clear Finished again when no finished items exist is a safe no-op
        app._on_clear_finished()
        assert len(app._queue_items) == 2

        # Mark remaining as SUCCESS and clear again to verify empty state restoration
        app._queue_items[id2].status = QueueItemStatus.SUCCESS
        app._queue_items[id2].result = OCRResult(file_path=id2, status=JobStatus.SUCCESS)
        app._queue_items[id3].status = QueueItemStatus.SUCCESS
        app._queue_items[id3].result = OCRResult(file_path=id3, status=JobStatus.SUCCESS)

        app._on_clear_finished()
        assert len(app._queue_items) == 0
        assert app._selected_item_id is None
        assert "No document selected" in app._tb_preview.get("1.0", "end")
        assert app._empty_queue_label.winfo_manager() == "pack"
    finally:
        app._on_closing()


def test_copy_to_clipboard(tmp_path):
    """Verify Copy to Clipboard copies markdown text and gives visual feedback."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        test_file = tmp_path / "notes.pdf"
        test_file.write_bytes(b"data")
        app.enqueue_file(test_file)

        file_id = str(test_file.resolve())
        item = app._queue_items[file_id]
        item.status = QueueItemStatus.SUCCESS
        item.result = OCRResult(
            file_path=file_id,
            status=JobStatus.SUCCESS,
            pages=[PageResult(page_num=1, markdown="## Sample Heading\n\nBody text")],
        )

        app._select_queue_item(file_id)
        assert app._btn_copy.cget("state") == "normal"

        app._on_copy_clipboard()
        clipboard_content = app.clipboard_get()
        assert "## Sample Heading" in clipboard_content
        assert "Body text" in clipboard_content
        assert app._btn_copy.cget("text") == "Copied!"
    finally:
        app._on_closing()


def test_export_selected_and_export_all_mocked(tmp_path):
    """Verify Export Selected and Export All pass expected signature parameters."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        f1 = tmp_path / "doc1.pdf"
        f2 = tmp_path / "doc2.png"
        f1.write_bytes(b"data1")
        f2.write_bytes(b"data2")

        app.enqueue_file(f1)
        app.enqueue_file(f2)

        id1 = str(f1.resolve())
        id2 = str(f2.resolve())

        res1 = OCRResult(file_path=id1, status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="# 1")])
        res2 = OCRResult(file_path=id2, status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="# 2")])

        app._queue_items[id1].status = QueueItemStatus.SUCCESS
        app._queue_items[id1].result = res1

        app._queue_items[id2].status = QueueItemStatus.SUCCESS
        app._queue_items[id2].result = res2

        app._select_queue_item(id1)
        assert app._btn_export_selected.cget("state") == "normal"
        assert app._btn_export_selected.cget("fg_color") == COLOR_ACCENT_PRIMARY
        assert app._btn_export_all.cget("state") == "normal"

        export_target = tmp_path / "export_output"
        export_target.mkdir()

        # 1. Export Selected
        with patch("gui.app.filedialog.askdirectory", return_value=str(export_target)), \
             patch("gui.app.save_artifacts", return_value=[export_target / "doc1.md"]) as mock_save:
            app._on_export_selected()
            mock_save.assert_called_once_with(
                res1,
                config=JobConfig(output_format=OutputFormat.BOTH),
                output_dir=export_target,
                base_name="doc1",
            )
            assert app._btn_export_selected.cget("text") == "Exported!"

        # 2. Export All
        with patch("gui.app.filedialog.askdirectory", return_value=str(export_target)), \
             patch("gui.app.save_artifacts", return_value=[export_target / "doc.md"]) as mock_save_all:
            app._on_export_all()
            app.wait_for_export()
            assert mock_save_all.call_count == 2
            mock_save_all.assert_has_calls([
                call(res1, config=JobConfig(output_format=OutputFormat.BOTH), output_dir=export_target, base_name="doc1"),
                call(res2, config=JobConfig(output_format=OutputFormat.BOTH), output_dir=export_target, base_name="doc2"),
            ], any_order=True)
            assert app._btn_export_all.cget("text") == "Exported All!"

        # 3. User cancels dialog -> save_artifacts not called
        with patch("gui.app.filedialog.askdirectory", return_value=""), \
             patch("gui.app.save_artifacts") as mock_cancel:
            app._on_export_selected()
            app._on_export_all()
            mock_cancel.assert_not_called()

    finally:
        app._on_closing()


def test_real_save_artifacts_integration_end_to_end(tmp_path):
    """Verify REAL core.formatter.save_artifacts is called without errors and writes to disk."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        f1 = tmp_path / "report.pdf"
        f1.write_bytes(b"dummy")
        app.enqueue_file(f1)

        file_id = str(f1.resolve())
        res = OCRResult(
            file_path=file_id,
            status=JobStatus.SUCCESS,
            pages=[PageResult(page_num=1, markdown="# Real End-to-End Export")],
        )
        app._queue_items[file_id].status = QueueItemStatus.SUCCESS
        app._queue_items[file_id].result = res

        app._select_queue_item(file_id)

        export_target = tmp_path / "actual_export"
        export_target.mkdir()

        # Real save_artifacts called directly (NO MOCK on save_artifacts!)
        with patch("gui.app.filedialog.askdirectory", return_value=str(export_target)):
            app._on_export_selected()

        md_file = export_target / "report.md"
        json_file = export_target / "report.json"

        assert md_file.exists(), f"Expected {md_file} to exist on disk"
        assert json_file.exists(), f"Expected {json_file} to exist on disk"
        assert "# Real End-to-End Export" in md_file.read_text(encoding="utf-8")
        assert '"page_num": 1' in json_file.read_text(encoding="utf-8")
        assert app._btn_export_selected.cget("text") == "Exported!"
    finally:
        app._on_closing()


def test_export_all_disambiguates_filename_collisions_end_to_end(tmp_path):
    """Verify Export All prevents silent overwrites when multiple files share the same filename stem."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        folder_a = tmp_path / "dept_a"
        folder_b = tmp_path / "dept_b"
        folder_c = tmp_path / "dept_c"
        folder_a.mkdir()
        folder_b.mkdir()
        folder_c.mkdir()

        file_a = folder_a / "invoice.pdf"
        file_b = folder_b / "invoice.pdf"
        file_c = folder_c / "invoice.pdf"
        file_a.write_bytes(b"a")
        file_b.write_bytes(b"b")
        file_c.write_bytes(b"c")

        app.enqueue_file(file_a)
        app.enqueue_file(file_b)
        app.enqueue_file(file_c)

        id_a, id_b, id_c = str(file_a.resolve()), str(file_b.resolve()), str(file_c.resolve())

        app._queue_items[id_a].status = QueueItemStatus.SUCCESS
        app._queue_items[id_a].result = OCRResult(file_path=id_a, status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="Invoice Dept A")])

        app._queue_items[id_b].status = QueueItemStatus.SUCCESS
        app._queue_items[id_b].result = OCRResult(file_path=id_b, status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="Invoice Dept B")])

        app._queue_items[id_c].status = QueueItemStatus.SUCCESS
        app._queue_items[id_c].result = OCRResult(file_path=id_c, status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="Invoice Dept C")])

        export_target = tmp_path / "batch_out"
        export_target.mkdir()

        # Execute Export All with real save_artifacts
        with patch("gui.app.filedialog.askdirectory", return_value=str(export_target)):
            app._on_export_all()
            app.wait_for_export()

        # Verify all 3 documents were preserved with unique non-colliding filenames
        file1_md = export_target / "invoice.md"
        file1_json = export_target / "invoice.json"
        file2_md = export_target / "invoice_2.md"
        file2_json = export_target / "invoice_2.json"
        file3_md = export_target / "invoice_3.md"
        file3_json = export_target / "invoice_3.json"

        assert file1_md.exists()
        assert file1_json.exists()
        assert file2_md.exists()
        assert file2_json.exists()
        assert file3_md.exists()
        assert file3_json.exists()

        # Verify content fidelity - NO SILENT OVERWRITES!
        assert "Invoice Dept A" in file1_md.read_text(encoding="utf-8")
        assert "Invoice Dept B" in file2_md.read_text(encoding="utf-8")
        assert "Invoice Dept C" in file3_md.read_text(encoding="utf-8")
    finally:
        app._on_closing()


def test_save_artifacts_signature_compatibility():
    """Verify inspect.signature of save_artifacts matches the arguments provided by OCRApp."""
    sig = inspect.signature(save_artifacts)
    params = list(sig.parameters.keys())

    # Ensure required signature parameters are present
    assert "result" in params
    assert "config" in params
    assert "output_dir" in params
    assert "base_name" in params

    # Confirm OCRResult and JobConfig are accepted without errors
    dummy_result = OCRResult(file_path="test.pdf", status=JobStatus.SUCCESS)
    dummy_config = JobConfig(output_format=OutputFormat.BOTH)

    bound = sig.bind(
        dummy_result,
        config=dummy_config,
        output_dir=Path("tmp"),
        base_name="custom_stem",
    )
    assert bound.arguments["result"] is dummy_result
    assert bound.arguments["config"] is dummy_config
    assert bound.arguments["base_name"] == "custom_stem"


def test_drop_zone_hover_enter_leave():
    """Verify drop zone border color brightens on mouse enter and reverts on leave."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # Initial state should be standard border
        assert app._drop_zone.cget("border_color") == COLOR_SURFACE_BORDER

        # Simulate enter
        event = SimpleNamespace(widget=app._drop_zone)
        app._on_drop_zone_enter(event)
        assert app._drop_zone.cget("border_color") == COLOR_SURFACE_BORDER_HOVER

        # Simulate leave
        app._on_drop_zone_leave(event)
        assert app._drop_zone.cget("border_color") == COLOR_SURFACE_BORDER
    finally:
        app._on_closing()


def test_drag_over_enter_leave():
    """Verify drag-over flips border to amber and tints background, reverting on leave."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # Initial state
        assert app._drop_zone.cget("border_color") == COLOR_SURFACE_BORDER
        assert app._drop_zone.cget("fg_color") == COLOR_SURFACE_1

        # Simulate drag enter with action
        event = SimpleNamespace(action="copy")
        action_ret = app._on_drag_enter(event)
        assert action_ret == "copy"
        assert app._drop_zone.cget("border_color") == COLOR_ACCENT_PRIMARY
        assert app._drop_zone.cget("fg_color") == COLOR_DRAGOVER_BG

        # Simulate drag leave
        action_ret_leave = app._on_drag_leave(event)
        assert action_ret_leave == "copy"
        assert app._drop_zone.cget("border_color") == COLOR_SURFACE_BORDER
        assert app._drop_zone.cget("fg_color") == COLOR_SURFACE_1
    finally:
        app._on_closing()


def test_queue_row_hover_enter_leave_and_selected_guard(tmp_path):
    """Verify queue row hover lightens background on unselected items and preserves selected item background."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        file_a = tmp_path / "first.pdf"
        file_b = tmp_path / "second.pdf"
        file_a.write_bytes(b"dummy1")
        file_b.write_bytes(b"dummy2")

        app.enqueue_file(file_a)
        app.enqueue_file(file_b)

        id_a = str(file_a.resolve())
        id_b = str(file_b.resolve())

        item_a = app._queue_items[id_a]
        item_b = app._queue_items[id_b]

        # file_a was first item, so it was auto-selected
        assert app._selected_item_id == id_a
        assert item_a.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG
        assert item_b.row_frame.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL

        # 1. Hover over unselected row (item_b): flips to COLOR_INTERACTIVE_HOVER
        event_b = SimpleNamespace(widget=item_b.row_frame, item_id=id_b)
        app._on_queue_row_enter(event_b, item_id=id_b)
        assert item_b.row_frame.cget("fg_color") == COLOR_INTERACTIVE_HOVER

        # 2. Leave unselected row (item_b): reverts to COLOR_INTERACTIVE_NEUTRAL
        app._on_queue_row_leave(event_b, item_id=id_b)
        assert item_b.row_frame.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL

        # 3. Hover over selected row (item_a): MUST NOT clobber COLOR_ROW_SELECTED_BG
        event_a = SimpleNamespace(widget=item_a.row_frame, item_id=id_a)
        app._on_queue_row_enter(event_a, item_id=id_a)
        assert item_a.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG

        # Leave selected row: still COLOR_ROW_SELECTED_BG
        app._on_queue_row_leave(event_a, item_id=id_a)
        assert item_a.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG

        # 4. Switch selection to item_b and verify roles swap
        app._select_queue_item(id_b)
        assert app._selected_item_id == id_b
        assert item_b.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG
        assert item_a.row_frame.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL

        # Hover over now-unselected item_a: flips to COLOR_INTERACTIVE_HOVER
        app._on_queue_row_enter(event_a, item_id=id_a)
        assert item_a.row_frame.cget("fg_color") == COLOR_INTERACTIVE_HOVER
        app._on_queue_row_leave(event_a, item_id=id_a)
        assert item_a.row_frame.cget("fg_color") == COLOR_INTERACTIVE_NEUTRAL

        # Hover over now-selected item_b: preserved as COLOR_ROW_SELECTED_BG
        app._on_queue_row_enter(event_b, item_id=id_b)
        assert item_b.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG
        app._on_queue_row_leave(event_b, item_id=id_b)
        assert item_b.row_frame.cget("fg_color") == COLOR_ROW_SELECTED_BG
    finally:
        app._on_closing()


def test_backend_badge_reads_from_engine_settings():
    """Verify backend badge displays engine.settings when settings arg is omitted."""
    custom_settings = Settings(
        backend="ollama",
        local_endpoint="http://localhost:11434/v1",
    )
    mock_engine = MagicMock()
    mock_engine.settings = custom_settings

    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        assert app._backend_badge.cget("text") == "Backend: ollama (http://localhost:11434/v1)"
        assert app.settings.backend == "ollama"
        assert app.settings.local_endpoint == "http://localhost:11434/v1"
    finally:
        app._on_closing()


def test_backend_badge_shows_remote_indicator():
    """Verify backend badge displays REMOTE BACKEND warning when connected to non-loopback endpoint."""
    remote_settings = Settings(
        backend="vllm",
        local_endpoint="http://192.168.1.150:8000/v1",
        allow_remote=True,
    )
    mock_engine = MagicMock()
    mock_engine.settings = remote_settings

    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        badge_text = app._backend_badge.cget("text")
        assert badge_text == "REMOTE BACKEND: vllm (http://192.168.1.150:8000/v1)"
        assert app.settings.is_loopback is False
        assert app.settings.allow_remote is True
    finally:
        app._on_closing()


def test_gui_cancellation_flow(tmp_path):
    """Verify GUI cancel button state, signal triggering, and CANCELLED event handling."""
    mock_engine = MagicMock()
    test_file = tmp_path / "long_doc.pdf"
    test_file.write_bytes(b"%PDF-1.4 dummy")

    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # Initially disabled
        assert app._btn_cancel.cget("state") == "disabled"
        assert "after current page" in app._btn_cancel.cget("text")

        app.enqueue_file(test_file)
        item_id = str(test_file.resolve())
        item = app._queue_items[item_id]

        # Simulate STARTED event
        app._result_queue.put(
            WorkerEvent(
                event_type=WorkerEventType.STARTED,
                file_path=item_id,
            )
        )
        app._process_result_queue()

        # Wire up a mock cancel event as would exist during in-flight processing
        import threading
        fake_cancel_event = threading.Event()
        app._current_cancel_event = fake_cancel_event
        app._update_action_buttons()

        assert app._btn_cancel.cget("state") == "normal"

        # User clicks cancel
        app._on_cancel_current()
        assert fake_cancel_event.is_set()
        assert app._btn_cancel.cget("state") == "disabled"
        assert app._btn_cancel.cget("text") == "Cancelling..."
        assert "Cancelling after current page" in app._footer_status.cget("text")

        # Simulate CANCELLED event from worker
        cancelled_result = OCRResult(
            file_path=item_id,
            cancelled=True,
            status=JobStatus.CANCELLED,
            error="Processing cancelled by user after page 1",
            pages=[PageResult(page_num=1, markdown="# Page 1 Done", status=JobStatus.SUCCESS)],
        )
        app._result_queue.put(
            WorkerEvent(
                event_type=WorkerEventType.CANCELLED,
                file_path=item_id,
                result=cancelled_result,
                error=cancelled_result.error,
            )
        )
        app._current_cancel_event = None
        app._process_result_queue()

        assert item.status == QueueItemStatus.CANCELLED
        assert item.badge_label.cget("text") == "●"
        assert item.badge_label.cget("text_color") == COLOR_STATUS_CANCELLED
        assert "Cancelled" in item.detail_label.cget("text")
        assert "Cancelled: long_doc.pdf" in app._footer_status.cget("text")

        # Active selection preview rendered
        app.select_tab("Text Preview")
        tb_content = app._tb_preview.get("1.0", "end")
        assert "Processing Cancelled: long_doc.pdf" in tb_content
        assert "# Page 1 Done" in tb_content

        # Clear finished includes cancelled items
        app._on_clear_finished()
        assert item_id not in app._queue_items
    finally:
        app._on_closing()


def test_gui_folder_drop_recursive_ingest(tmp_path: Path) -> None:
    """Verify dropping a folder discovers and enqueues supported files recursively (Finding 1.3)."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        drop_folder = tmp_path / "dropped_batch"
        sub_folder = drop_folder / "sub"
        sub_folder.mkdir(parents=True)

        doc1 = drop_folder / "doc1.pdf"
        doc1.write_bytes(b"%PDF-1.4 dummy 1")

        img1 = sub_folder / "scan.png"
        img1.write_bytes(b"\x89PNG dummy 2")

        unsupported_doc = sub_folder / "notes.docx"
        unsupported_doc.write_bytes(b"PK dummy 3")

        # Enqueue the directory
        app.enqueue_file(drop_folder)
        app.wait_for_ingest()

        # The folder itself must NOT be queued
        assert str(drop_folder.resolve()) not in app._queue_items

        # Supported children must be queued
        assert str(doc1.resolve()) in app._queue_items
        assert str(img1.resolve()) in app._queue_items

        # Unsupported files must be skipped
        assert str(unsupported_doc.resolve()) not in app._queue_items
        assert len(app._queue_items) == 2

        # Test empty folder drop
        empty_folder = tmp_path / "empty_folder"
        empty_folder.mkdir()
        app.enqueue_file(empty_folder)
        app.wait_for_ingest()
        assert "No supported documents in empty_folder" in app._footer_status.cget("text")
        assert len(app._queue_items) == 2
    finally:
        app._on_closing()


def test_queue_item_file_type_chips(tmp_path: Path) -> None:
    """Verify queue items render distinct PDF and IMG file-type chips."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        pdf_file = tmp_path / "invoice.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 dummy")
        png_file = tmp_path / "diagram.png"
        png_file.write_bytes(b"\x89PNG dummy")

        app.enqueue_file(pdf_file)
        app.enqueue_file(png_file)

        pdf_item = app._queue_items[str(pdf_file.resolve())]
        png_item = app._queue_items[str(png_file.resolve())]

        assert pdf_item.chip_label is not None
        assert pdf_item.chip_label.cget("text") == "PDF"

        assert png_item.chip_label is not None
        assert png_item.chip_label.cget("text") == "IMG"
    finally:
        app._on_closing()


def test_footer_trust_indicator() -> None:
    """Verify the footer displays the Local Processing trust indicator."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        assert hasattr(app, "_trust_label")
        assert "Local Processing" in app._trust_label.cget("text")
        assert "stays on your device" in app._trust_label.cget("text")
    finally:
        app._on_closing()


def test_calm_trust_color_tokens() -> None:
    """Verify calm trust palette color token hex values."""
    assert COLOR_CANVAS_BG == "#121417"
    assert COLOR_ACCENT_PRIMARY == "#2e6e91"
    assert COLOR_TEXT_PRIMARY == "#f1f3f5"
    assert COLOR_CHIP_PDF_BG == "#331e24"
    assert COLOR_CHIP_IMG_BG == "#182c3d"


def test_four_tabview_structure() -> None:
    """Verify preview tabview contains the four Stage C tabs."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        tab_names = [
            app._tabview._tab_dict[k]._name
            for k in app._tabview._tab_dict
        ]
        # In CTkTabview, tab keys or names correspond to the added tabs
        assert "Raw Markdown" in app._tabview._tab_dict
        assert "Text Preview" in app._tabview._tab_dict
        assert "Image Preview" in app._tabview._tab_dict
        assert "JSON Tree" in app._tabview._tab_dict

        # Verify widget bindings exist
        assert hasattr(app, "_tb_markdown")
        assert hasattr(app, "_tb_preview")
        assert hasattr(app, "_img_scroll")
        assert hasattr(app, "_img_display_label")
        assert hasattr(app, "_tb_json")
        assert hasattr(app, "_progress_bar")
        assert hasattr(app, "_lbl_page_counter")
    finally:
        app._on_closing()


def test_markdown_preview_graceful_fallback() -> None:
    """Verify malformed markdown (broken tables, unclosed fences/formatting) degrades cleanly to plain text."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # 1. Normal markdown renders with tags
        valid_md = "# Title\n\nThis is **bold** and *italic* and `code`.\n\n| Col 1 | Col 2 |\n|---|---|\n| Val 1 | Val 2 |\n"
        app._render_markdown_preview(valid_md)
        content = app._tb_preview.get("1.0", "end")
        assert "Title" in content
        assert "bold" in content
        assert "Val 1" in content

        # 2. Deliberately broken markdown (unclosed fences, broken table pipes, dangling tokens)
        malformed_md = (
            "# Broken Doc\n\n"
            "```python\n"
            "unclosed code block without ending fence\n"
            "| Ragged Table Header | Missing Closing Pipe\n"
            "|---|---|---\n"
            "| Cell 1 | Cell 2 | Extra cell\n"
            "| Incomplete row\n"
            "**unclosed bold text\n"
            "*unclosed italic text\n"
            "`unclosed inline code\n"
            "--- horizontal divider\n"
        )
        # Should not raise exception
        app._render_markdown_preview(malformed_md)
        fallback_content = app._tb_preview.get("1.0", "end")
        assert "Broken Doc" in fallback_content
        assert "unclosed code block without ending fence" in fallback_content
        assert "Ragged Table Header" in fallback_content
        assert fallback_content.strip() != ""

        # 3. Explicit exception in _apply_markdown_tags falls back to plain text
        with patch.object(app, "_apply_markdown_tags", side_effect=RuntimeError("Simulated tag failure")):
            app._render_markdown_preview("# Still Works\nEven after a parser crash.")
            crash_content = app._tb_preview.get("1.0", "end")
            assert "Still Works" in crash_content
            assert "Even after a parser crash." in crash_content
    finally:
        app._on_closing()


def test_page_progress_worker_event_wiring(tmp_path: Path) -> None:
    """Verify PAGE_PROGRESS WorkerEvent updates CTkProgressBar, page counter, and preview incrementally."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        test_file = tmp_path / "multipage.pdf"
        test_file.write_bytes(b"%PDF-1.4 multipage dummy")
        app.enqueue_file(test_file)
        item_id = str(test_file.resolve())
        item = app._queue_items[item_id]

        # 1. Simulate STARTED event
        app._result_queue.put(
            WorkerEvent(
                event_type=WorkerEventType.STARTED,
                file_path=item_id,
            )
        )
        app._process_result_queue()
        assert app._progress_bar.get() == 0.0

        # 2. Simulate PAGE_PROGRESS event (page 1 of 3)
        page1_res = PageResult(page_num=1, markdown="# Page 1 Content", status=JobStatus.SUCCESS)
        app._result_queue.put(
            WorkerEvent(
                event_type=WorkerEventType.PAGE_PROGRESS,
                file_path=item_id,
                current_page=1,
                total_pages=3,
                page_result=page1_res,
            )
        )
        app._process_result_queue()
        assert pytest.approx(app._progress_bar.get(), rel=1e-2) == 1.0 / 3.0
        assert app._lbl_page_counter.cget("text") == "Page 1 of 3"
        assert "Page 1/3" in app._footer_status.cget("text")

        # 3. Simulate PAGE_PROGRESS event (page 2 of 3)
        page2_res = PageResult(page_num=2, markdown="# Page 2 Content", status=JobStatus.SUCCESS)
        app._result_queue.put(
            WorkerEvent(
                event_type=WorkerEventType.PAGE_PROGRESS,
                file_path=item_id,
                current_page=2,
                total_pages=3,
                page_result=page2_res,
            )
        )
        app._process_result_queue()
        assert pytest.approx(app._progress_bar.get(), rel=1e-2) == 2.0 / 3.0
        assert app._lbl_page_counter.cget("text") == "Page 2 of 3"

        # 4. Simulate COMPLETED event
        complete_result = OCRResult(
            file_path=item_id,
            status=JobStatus.SUCCESS,
            pages=[page1_res, page2_res, PageResult(page_num=3, markdown="# Page 3 Content")],
        )
        app._result_queue.put(
            WorkerEvent(
                event_type=WorkerEventType.COMPLETED,
                file_path=item_id,
                result=complete_result,
            )
        )
        app._process_result_queue()
        assert app._progress_bar.get() == 1.0
        assert "done" in app._lbl_page_counter.cget("text")
    finally:
        app._on_closing()


def test_image_preview_pagination(tmp_path: Path) -> None:
    """Verify Image Preview displays images and responds to < Prev / Next > pagination."""
    from PIL import Image

    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        test_file = tmp_path / "scan_book.tiff"
        frame1 = Image.new("RGB", (60, 60), color="red")
        frame2 = Image.new("RGB", (60, 60), color="green")
        frame3 = Image.new("RGB", (60, 60), color="blue")
        frame1.save(test_file, format="TIFF", save_all=True, append_images=[frame2, frame3])
        app.enqueue_file(test_file)
        item_id = str(test_file.resolve())
        item = app._queue_items[item_id]

        # Initial state before processing: no images
        app.select_tab("Image Preview")
        assert app._lbl_img_page.cget("text") == "Page 0 of 0"
        assert app._btn_img_prev.cget("state") == "disabled"
        assert app._btn_img_next.cget("state") == "disabled"

        # Attach result with 3 image pages
        result = OCRResult(
            file_path=item_id,
            status=JobStatus.SUCCESS,
            pages=[
                PageResult(page_num=1, markdown="# P1"),
                PageResult(page_num=2, markdown="# P2"),
                PageResult(page_num=3, markdown="# P3"),
            ],
        )
        item.status = QueueItemStatus.SUCCESS
        item.result = result

        # Render preview: should start on page 1 of 3
        app._current_image_page_idx = 0
        app.select_tab("Image Preview")

        assert app._lbl_img_page.cget("text") == "Page 1 of 3"
        assert app._btn_img_prev.cget("state") == "disabled"
        assert app._btn_img_next.cget("state") == "normal"
        assert "60 × 60 px" in app._lbl_img_info.cget("text")

        # Next page -> Page 2 of 3
        app._on_img_next()
        assert app._current_image_page_idx == 1
        assert app._lbl_img_page.cget("text") == "Page 2 of 3"
        assert app._btn_img_prev.cget("state") == "normal"
        assert app._btn_img_next.cget("state") == "normal"

        # Next page -> Page 3 of 3 (last page)
        app._on_img_next()
        assert app._current_image_page_idx == 2
        assert app._lbl_img_page.cget("text") == "Page 3 of 3"
        assert app._btn_img_prev.cget("state") == "normal"
        assert app._btn_img_next.cget("state") == "disabled"

        # Prev page -> Page 2 of 3
        app._on_img_prev()
        assert app._current_image_page_idx == 1
        assert app._lbl_img_page.cget("text") == "Page 2 of 3"
        assert app._btn_img_prev.cget("state") == "normal"
        assert app._btn_img_next.cget("state") == "normal"
    finally:
        app._on_closing()


def test_settings_window_initialization_and_population():
    """Verify SettingsWindow initializes and accurately populates from Settings."""
    from gui.settings_window import SettingsWindow

    parent = ctk.CTk()
    parent.withdraw()

    initial = Settings(
        backend="ollama",
        local_endpoint="http://localhost:11434/v1",
        timeout=45.0,
        max_retries=3,
        allow_remote=False,
        llama_server_path=r"C:\bin\llama-server.exe",
        model_repo="custom/repo",
        auto_start_server=True,
        dpi=120,
        max_pages=15,
    )

    win = SettingsWindow(parent, settings=initial)
    try:
        assert win._seg_backend.get() == "ollama"
        assert win._ent_endpoint.get() == "http://localhost:11434/v1"
        assert win._sw_allow_remote.get() == 0
        assert win._ent_timeout.get() == "45.0"
        assert win._ent_retries.get() == "3"
        assert int(win._slider_dpi.get()) == 120
        assert win._ent_max_pages.get() == "15"
        assert win._ent_server_path.get() == r"C:\bin\llama-server.exe"
        assert win._ent_model_repo.get() == "custom/repo"
        assert win._sw_auto_start.get() == 1
    finally:
        win.destroy()
        parent.destroy()


def test_settings_window_validation_rejection_bad_timeout():
    """Verify entering an invalid timeout surfaces a validation error and aborts save."""
    from gui.settings_window import SettingsWindow

    parent = ctk.CTk()
    parent.withdraw()

    initial = Settings()
    mock_callback = MagicMock()
    win = SettingsWindow(parent, settings=initial, on_save_callback=mock_callback)

    try:
        win._ent_timeout.delete(0, "end")
        win._ent_timeout.insert(0, "-5.0")  # Invalid negative timeout

        win._on_save()

        # Error banner shown
        error_text = win._lbl_error_banner.cget("text")
        assert "Validation Error" in error_text
        assert "TIMEOUT must be a positive number" in error_text

        # Callback must NOT be invoked
        mock_callback.assert_not_called()
    finally:
        win.destroy()
        parent.destroy()


def test_settings_window_validation_rejection_remote_endpoint():
    """Verify non-loopback endpoint without allow_remote is rejected by __post_init__."""
    from gui.settings_window import SettingsWindow

    parent = ctk.CTk()
    parent.withdraw()

    initial = Settings()
    mock_callback = MagicMock()
    win = SettingsWindow(parent, settings=initial, on_save_callback=mock_callback)

    try:
        win._ent_endpoint.delete(0, "end")
        win._ent_endpoint.insert(0, "http://192.168.1.200:8080/v1")  # Remote IP

        win._on_save()

        error_text = win._lbl_error_banner.cget("text")
        assert "Validation Error" in error_text
        assert "Security violation: Non-loopback endpoint" in error_text
        mock_callback.assert_not_called()
    finally:
        win.destroy()
        parent.destroy()


def test_settings_window_allow_remote_confirmation_flow():
    """Verify toggling allow_remote asks for confirmation and reverts on cancel."""
    from gui.settings_window import SettingsWindow

    parent = ctk.CTk()
    parent.withdraw()

    initial = Settings()
    win = SettingsWindow(parent, settings=initial)

    try:
        # 1. User toggles ON but clicks CANCEL in confirmation modal -> reverts to 0
        win._sw_allow_remote.select()
        with patch("gui.settings_window.SecurityConfirmationDialog.ask_confirmation", return_value=False):
            win._on_toggle_allow_remote()
            assert win._sw_allow_remote.get() == 0

        # 2. User toggles ON and clicks CONFIRM -> stays 1
        win._sw_allow_remote.select()
        with patch("gui.settings_window.SecurityConfirmationDialog.ask_confirmation", return_value=True):
            win._on_toggle_allow_remote()
            assert win._sw_allow_remote.get() == 1
    finally:
        win.destroy()
        parent.destroy()


def test_settings_window_successful_save(tmp_path):
    """Verify valid settings save to .env and invoke the on_save_callback."""
    from gui.settings_window import SettingsWindow

    parent = ctk.CTk()
    parent.withdraw()

    initial = Settings()
    saved_instances = []

    def _on_save(s: Settings):
        saved_instances.append(s)

    win = SettingsWindow(parent, settings=initial, on_save_callback=_on_save)

    try:
        win._ent_timeout.delete(0, "end")
        win._ent_timeout.insert(0, "90.0")

        win._slider_dpi.set(150)

        with patch("config.settings.Settings.save_to_env") as mock_save_env:
            win._on_save()
            mock_save_env.assert_called_once()

        assert len(saved_instances) == 1
        assert saved_instances[0].timeout == 90.0
        assert saved_instances[0].dpi == 150
    finally:
        try:
            win.destroy()
        except Exception:
            pass
        parent.destroy()


def test_settings_window_cancel_and_close_discards_changes(tmp_path: Path):
    """Verify Cancel and window close discard unsaved form edits without touching .env or os.environ."""
    import os
    from gui.settings_window import SettingsWindow

    parent = ctk.CTk()
    parent.withdraw()

    initial = Settings(
        backend="llama-cpp",
        local_endpoint="http://127.0.0.1:8080/v1",
        timeout=30.0,
        max_retries=1,
        dpi=100,
    )
    mock_callback = MagicMock()

    # Create dummy .env file
    env_file = tmp_path / ".env"
    initial.save_to_env(env_path=env_file)
    initial_env_content = env_file.read_text(encoding="utf-8")
    initial_os_timeout = os.environ.get("OCR_TIMEOUT")

    # 1. Test _on_cancel() discard
    win = SettingsWindow(parent, settings=initial, on_save_callback=mock_callback)
    try:
        # User makes edits in the form
        win._ent_timeout.delete(0, "end")
        win._ent_timeout.insert(0, "120.0")
        win._slider_dpi.set(200)
        win._ent_endpoint.delete(0, "end")
        win._ent_endpoint.insert(0, "http://127.0.0.1:9999/v1")

        # User clicks Cancel
        win._on_cancel()

        # Verify nothing touched
        mock_callback.assert_not_called()
        assert env_file.read_text(encoding="utf-8") == initial_env_content
        assert os.environ.get("OCR_TIMEOUT") == initial_os_timeout
    finally:
        try:
            win.destroy()
        except Exception:
            pass

    # 2. Test WM_DELETE_WINDOW (window 'X' button protocol) discard
    win2 = SettingsWindow(parent, settings=initial, on_save_callback=mock_callback)
    try:
        win2._ent_timeout.delete(0, "end")
        win2._ent_timeout.insert(0, "999.0")

        # Simulate clicking the 'X' button (invokes WM_DELETE_WINDOW handler)
        win2._on_cancel()

        mock_callback.assert_not_called()
        assert env_file.read_text(encoding="utf-8") == initial_env_content
        assert os.environ.get("OCR_TIMEOUT") == initial_os_timeout
    finally:
        try:
            win2.destroy()
        except Exception:
            pass
        parent.destroy()


def test_server_status_pill_and_button_rendering():
    """Verify header status pill and server action button update for all status states."""
    from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo

    mock_engine = MagicMock()
    mock_sm = MagicMock()
    mock_sm.get_status_info.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
        endpoint="http://127.0.0.1:8080/v1",
    )

    app = OCRApp(engine=mock_engine, server_manager=mock_sm)
    app.withdraw()

    try:
        # 1. OFFLINE
        app._apply_server_status_update(
            ServerStatusInfo(status=ServerStatus.OFFLINE, ownership=ServerOwnership.NONE, message="Offline")
        )
        assert app._server_status_pill.cget("text") == "● OFFLINE"
        assert app._btn_server_action.cget("text") == "Start Server"
        assert str(app._btn_server_action.cget("state")) == "normal"

        # 2a. STARTING (External / None)
        app._apply_server_status_update(
            ServerStatusInfo(status=ServerStatus.STARTING, ownership=ServerOwnership.NONE, message="Booting")
        )
        assert app._server_status_pill.cget("text") == "● STARTING"
        assert app._btn_server_action.cget("text") == "Starting..."
        assert str(app._btn_server_action.cget("state")) == "disabled"

        # 2b. STARTING (Managed) -> Cancel Launch
        app._apply_server_status_update(
            ServerStatusInfo(status=ServerStatus.STARTING, ownership=ServerOwnership.MANAGED, message="Booting")
        )
        assert app._server_status_pill.cget("text") == "● STARTING"
        assert app._btn_server_action.cget("text") == "Cancel Launch"
        assert str(app._btn_server_action.cget("state")) == "normal"

        # 3. READY (Managed)
        app._apply_server_status_update(
            ServerStatusInfo(status=ServerStatus.READY, ownership=ServerOwnership.MANAGED, message="Ready")
        )
        assert app._server_status_pill.cget("text") == "● READY (Managed)"
        assert app._btn_server_action.cget("text") == "Stop Server"
        assert str(app._btn_server_action.cget("state")) == "normal"

        # 4. READY (External)
        app._apply_server_status_update(
            ServerStatusInfo(status=ServerStatus.READY, ownership=ServerOwnership.EXTERNAL, message="Ready")
        )
        assert app._server_status_pill.cget("text") == "● READY (Ext)"
        assert app._btn_server_action.cget("text") == "External"
        assert str(app._btn_server_action.cget("state")) == "disabled"

        # 5. ERROR
        app._apply_server_status_update(
            ServerStatusInfo(status=ServerStatus.ERROR, ownership=ServerOwnership.NONE, message="Failed")
        )
        assert app._server_status_pill.cget("text") == "● ERROR"
        assert app._btn_server_action.cget("text") == "Start Server"
        assert str(app._btn_server_action.cget("state")) == "normal"

    finally:
        app._on_closing()


def test_server_action_button_click_dispatches_start_and_stop():
    """Verify clicking the server action button dispatches start() or stop() as appropriate."""
    from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo

    mock_engine = MagicMock()
    mock_sm = MagicMock()
    mock_sm.get_status_info.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )

    app = OCRApp(engine=mock_engine, server_manager=mock_sm)
    app.withdraw()

    try:
        # Case A: When offline, click triggers start()
        mock_sm.status = ServerStatus.OFFLINE
        mock_sm.ownership = ServerOwnership.NONE
        app._on_server_action_clicked()
        time.sleep(0.1)
        assert mock_sm.start.call_count == 1

        # Case B: When ready and managed, click triggers stop()
        mock_sm.status = ServerStatus.READY
        mock_sm.ownership = ServerOwnership.MANAGED
        app._on_server_action_clicked()
        time.sleep(0.1)
        assert mock_sm.stop.call_count == 1

        # Case C: When starting and managed, click also triggers stop() (Cancel Launch)
        mock_sm.status = ServerStatus.STARTING
        mock_sm.ownership = ServerOwnership.MANAGED
        app._on_server_action_clicked()
        time.sleep(0.1)
        assert mock_sm.stop.call_count == 2
    finally:
        app._on_closing()


def test_server_auto_start_on_launch():
    """Verify auto_start_server=True triggers start() on launch if server is offline."""
    from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo

    mock_engine = MagicMock()

    # 1. auto_start_server = False -> start() not called
    mock_sm_no_auto = MagicMock()
    mock_sm_no_auto.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )
    s_false = Settings(auto_start_server=False)
    app_false = OCRApp(settings=s_false, engine=mock_engine, server_manager=mock_sm_no_auto)
    app_false.withdraw()
    try:
        mock_sm_no_auto.start.assert_not_called()
    finally:
        app_false._on_closing()

    # 2. auto_start_server = True -> start() called if offline
    mock_sm_auto = MagicMock()
    mock_sm_auto.poll_status.return_value = ServerStatusInfo(
        status=ServerStatus.OFFLINE,
        ownership=ServerOwnership.NONE,
        message="Offline",
    )
    s_true = Settings(auto_start_server=True)
    app_true = OCRApp(settings=s_true, engine=mock_engine, server_manager=mock_sm_auto)
    app_true.withdraw()
    try:
        mock_sm_auto.start.assert_called_once()
    finally:
        app_true._on_closing()


def test_server_manager_cleanup_on_closing():
    """Verify _on_closing terminates managed server and closes sessions."""
    mock_engine = MagicMock()
    mock_sm = MagicMock()
    mock_sm.is_managed = True

    app = OCRApp(engine=mock_engine, server_manager=mock_sm)
    app.withdraw()

    app._on_closing()

    assert mock_sm.stop.call_count == 1
    assert mock_sm.close.call_count == 1


def test_settings_dialog_opening_and_runtime_sync():
    """Verify clicking Settings button opens SettingsWindow and saving synchronizes engine/server state."""
    mock_engine = MagicMock()
    mock_engine.client = MagicMock()
    mock_sm = MagicMock()

    app = OCRApp(settings=Settings(), engine=mock_engine, server_manager=mock_sm)
    app.withdraw()

    try:
        # 1. Open settings window
        app._open_settings_dialog()
        assert app._settings_window is not None
        assert app._settings_window.winfo_exists()

        # 2. Saving new settings synchronizes app, server_manager, and engine
        new_settings = Settings(
            backend="ollama",
            local_endpoint="http://127.0.0.1:11434/v1",
            timeout=40.0,
            max_retries=3,
        )
        app._on_settings_saved(new_settings)

        assert app.settings.backend == "ollama"
        assert app.server_manager.settings.backend == "ollama"
        assert app.engine.settings.backend == "ollama"
        assert app.engine.client.endpoint == "http://127.0.0.1:11434/v1/chat/completions"
        assert app.engine.client.settings.timeout == 40.0
        assert app.engine.client.settings.max_retries == 3
        assert "Backend: ollama" in app._backend_badge.cget("text")

        # 3. Settings update deferred during active processing (SEC-3.1)
        fake_cancel = threading.Event()
        app._current_cancel_event = fake_cancel
        in_flight_settings = Settings(
            backend="vllm",
            local_endpoint="http://127.0.0.1:8000/v1",
            timeout=25.0,
        )
        app._on_settings_saved(in_flight_settings)
        # Should be queued in _pending_engine_settings, not immediately applied to client
        assert app._pending_engine_settings == in_flight_settings
        assert app.engine.client.endpoint == "http://127.0.0.1:11434/v1/chat/completions"

        # Simulating document completion and next document start
        app._current_cancel_event = None
        app._apply_pending_engine_settings()
        assert app._pending_engine_settings is None
        assert app.engine.client.endpoint == "http://127.0.0.1:8000/v1/chat/completions"
        assert app.engine.settings.backend == "vllm"
    finally:
        app._on_closing()


def test_queue_item_badges_use_dots_never_brackets(tmp_path):
    """Regression test asserting queue items use colored dots (●) and NEVER bracket badges ([✓], [>], [✗], [ ])."""
    p_queued = tmp_path / "queued_doc.pdf"
    p_proc = tmp_path / "processing_doc.pdf"
    p_success = tmp_path / "success_doc.pdf"
    p_failed = tmp_path / "failed_doc.pdf"
    p_cancelled = tmp_path / "cancelled_doc.pdf"

    for p in (p_queued, p_proc, p_success, p_failed, p_cancelled):
        p.write_bytes(b"dummy content")

    mock_engine = MagicMock()
    app = OCRApp(settings=Settings(), engine=mock_engine)
    app.withdraw()

    # Prevent background thread execution during deterministic event testing
    app._task_queue.put = lambda item, *args, **kwargs: None

    try:
        app.enqueue_file(p_queued)
        app.enqueue_file(p_proc)
        app.enqueue_file(p_success)
        app.enqueue_file(p_failed)
        app.enqueue_file(p_cancelled)

        id_queued = str(p_queued.resolve())
        id_proc = str(p_proc.resolve())
        id_success = str(p_success.resolve())
        id_failed = str(p_failed.resolve())
        id_cancelled = str(p_cancelled.resolve())

        # Transition items to their distinct statuses
        app._handle_worker_event(WorkerEvent(WorkerEventType.STARTED, file_path=id_proc))
        app._handle_worker_event(
            WorkerEvent(
                WorkerEventType.COMPLETED,
                file_path=id_success,
                result=OCRResult(
                    file_path=id_success,
                    status=JobStatus.SUCCESS,
                    pages=[PageResult(page_num=1, markdown="text", latency=0.1)],
                ),
            )
        )
        app._handle_worker_event(WorkerEvent(WorkerEventType.FAILED, file_path=id_failed, error="Mock decode failure"))
        app._handle_worker_event(WorkerEvent(WorkerEventType.CANCELLED, file_path=id_cancelled, error="User cancelled"))

        # Verify all lifecycle states
        bracket_literals = ("[✓]", "[>]", "[✗]", "[ ]", "[-]")
        for item_id, item in app._queue_items.items():
            badge_text = item.badge_label.cget("text")
            detail_text = item.detail_label.cget("text")

            # 1. Badge must strictly be the solid dot indicator (●)
            assert badge_text == "●", f"Item {item_id} badge text was {badge_text!r}, expected '●'"

            # 2. No bracket badge literals anywhere in row labels
            assert not any(b in badge_text for b in bracket_literals)
            assert not any(b in detail_text for b in bracket_literals)
            assert "[" not in badge_text and "]" not in badge_text

            # 3. Check all child labels inside the row widget
            for child in item.row_frame.winfo_children():
                if isinstance(child, ctk.CTkLabel):
                    lbl_text = child.cget("text")
                    assert not any(b in lbl_text for b in bracket_literals)
    finally:
        app._on_closing()


def test_batch2_lazy_tab_rendering_lifecycle(tmp_path):
    """P1: Verify that on progress/render events only the active tab is updated,
    and switching tabs renders the inactive tab on-demand."""
    p = tmp_path / "sample.pdf"
    p.write_bytes(b"%PDF-1.4 mock")
    app = OCRApp(settings=Settings(), engine=MagicMock())
    app.withdraw()
    app._task_queue.put = lambda item, *args, **kwargs: None

    try:
        app.enqueue_file(p)
        item_id = str(p.resolve())
        item = app._queue_items[item_id]
        app._select_queue_item(item_id)

        # Tabview defaults to "Raw Markdown"
        assert app._tabview.get() == "Raw Markdown"

        # Fire page progress
        app._handle_worker_event(
            WorkerEvent(
                WorkerEventType.PAGE_PROGRESS,
                file_path=item_id,
                current_page=1,
                total_pages=1,
                page_result=PageResult(page_num=1, markdown="# Markdown Content Heading"),
            )
        )

        # 1. Raw Markdown tab must be updated
        raw_text = app._tb_markdown.get("1.0", "end").strip()
        assert "# Markdown Content Heading" in raw_text

        # 2. Inactive tabs must NOT have been rendered yet
        rich_text = app._tb_preview.get("1.0", "end").strip()
        assert rich_text == "" or "Markdown Content Heading" not in rich_text

        # 3. Switching tabs triggers on-demand rendering
        app.select_tab("Text Preview")
        assert app._tabview.get() == "Text Preview"
        rich_text_after = app._tb_preview.get("1.0", "end").strip()
        assert "Markdown Content Heading" in rich_text_after

        # 4. JSON Tree tab still not rendered until switched
        json_text = app._tb_json.get("1.0", "end").strip()
        assert json_text == "" or "Markdown Content Heading" not in json_text

        app.select_tab("JSON Tree")
        assert app._tabview.get() == "JSON Tree"
        json_text_after = app._tb_json.get("1.0", "end").strip()
        assert "pages" in json_text_after or "Markdown Content Heading" in json_text_after
    finally:
        app._on_closing()


def test_batch2_on_demand_image_loading_and_fallback(tmp_path):
    """P2: Verify on-demand image loading from disk when image_b64 is None (both PDF and PNG),
    and verify missing source file displays 'Source file unavailable' gracefully."""
    from PIL import Image
    import pypdfium2 as pdfium

    # 1. Create a 2-page PDF
    pdf_path = tmp_path / "multipage.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 200)
    doc.new_page(200, 200)
    doc.save(str(pdf_path))
    doc.close()

    app = OCRApp(settings=Settings(), engine=MagicMock())
    app.withdraw()
    app._task_queue.put = lambda item, *args, **kwargs: None

    try:
        app.enqueue_file(pdf_path)
        item_id = str(pdf_path.resolve())
        item = app._queue_items[item_id]
        app._select_queue_item(item_id)

        # Complete with 2 pages and NO base64 images
        res = OCRResult(
            file_path=item_id,
            status=JobStatus.SUCCESS,
            pages=[
                PageResult(page_num=1, markdown="Page 1 text"),
                PageResult(page_num=2, markdown="Page 2 text"),
            ],
        )
        app._handle_worker_event(WorkerEvent(WorkerEventType.COMPLETED, file_path=item_id, result=res))

        # Switch to Image Preview tab
        app.select_tab("Image Preview")
        assert app._lbl_img_page.cget("text") == "Page 1 of 2"
        assert app._img_display_label.cget("image") is not None

        # Next page
        app._on_img_next()
        assert app._lbl_img_page.cget("text") == "Page 2 of 2"
        assert app._img_display_label.cget("image") is not None

        # Previous page
        app._on_img_prev()
        assert app._lbl_img_page.cget("text") == "Page 1 of 2"

        # Standalone image (PNG)
        png_path = tmp_path / "standalone.png"
        img = Image.new("RGB", (150, 150), color="red")
        img.save(png_path)

        app.enqueue_file(png_path)
        png_id = str(png_path.resolve())
        png_res = OCRResult(
            file_path=png_id,
            status=JobStatus.SUCCESS,
            pages=[PageResult(page_num=1, markdown="PNG text")],
        )
        app._handle_worker_event(WorkerEvent(WorkerEventType.COMPLETED, file_path=png_id, result=png_res))

        app._select_queue_item(png_id)
        assert app._tabview.get() == "Image Preview"
        assert app._lbl_img_page.cget("text") == "Page 1 of 1"
        assert app._img_display_label.cget("image") is not None

        # Fallback when source file is deleted/moved
        png_path.unlink()
        app._render_preview(app._queue_items[png_id], tab_name="Image Preview")
        assert not app._img_display_label.cget("image")
        assert "Source file unavailable" in app._img_display_label.cget("text")
    finally:
        app._on_closing()


def test_batch2_queue_item_file_size_caching(tmp_path):
    """P10: Verify QueueItem caches formatted file size at creation time,
    preventing repeated stat() calls during lifecycle events."""
    test_file = tmp_path / "cached_size_test.png"
    test_file.write_bytes(b"x" * 2048)

    app = OCRApp(settings=Settings(), engine=MagicMock())
    app.withdraw()
    app._task_queue.put = lambda item, *args, **kwargs: None

    try:
        app.enqueue_file(test_file)
        item_id = str(test_file.resolve())
        item = app._queue_items[item_id]

        assert item.file_size_str is not None
        assert "2.0 KB" in item.file_size_str or "2 KB" in item.file_size_str

        # Mock stat() to raise if called again
        with patch.object(Path, "stat", side_effect=RuntimeError("stat() should not be called")):
            # 1. format meta
            meta = app._format_queue_item_meta(item)
            assert item.file_size_str in meta

            # 2. lifecycle events
            app._handle_worker_event(WorkerEvent(WorkerEventType.STARTED, file_path=item_id))
            assert item.file_size_str in item.detail_label.cget("text")

            app._handle_worker_event(
                WorkerEvent(
                    WorkerEventType.PAGE_PROGRESS,
                    file_path=item_id,
                    current_page=1,
                    total_pages=1,
                    page_result=PageResult(page_num=1, markdown="Done"),
                )
            )
            assert item.file_size_str in item.detail_label.cget("text")

            res = OCRResult(
                file_path=item_id,
                status=JobStatus.SUCCESS,
                pages=[PageResult(page_num=1, markdown="Done", latency=0.1)],
            )
            app._handle_worker_event(WorkerEvent(WorkerEventType.COMPLETED, file_path=item_id, result=res))
            assert item.file_size_str in item.detail_label.cget("text")
    finally:
        app._on_closing()


def test_batch2_gui_item_selection_vs_worker_race_reverified(tmp_path):
    """Verify GUI item selection vs worker race:
    When user selects item B while worker is emitting events for item A,
    item B's preview is never clobbered, and tab switches on item B
    render item B's data on-demand (never item A's data)."""
    p_a = tmp_path / "item_a.pdf"
    p_b = tmp_path / "item_b.pdf"
    p_a.write_bytes(b"%PDF-1.4 a")
    p_b.write_bytes(b"%PDF-1.4 b")

    app = OCRApp(settings=Settings(), engine=MagicMock())
    app.withdraw()
    app._task_queue.put = lambda item, *args, **kwargs: None

    try:
        app.enqueue_file(p_a)
        app.enqueue_file(p_b)
        id_a = str(p_a.resolve())
        id_b = str(p_b.resolve())

        # Initially select item A
        app._select_queue_item(id_a)
        assert app._selected_item_id == id_a

        # Switch selection to item B
        app._select_queue_item(id_b)
        assert app._selected_item_id == id_b

        # Worker emits PAGE_PROGRESS and COMPLETED for item A
        res_a = OCRResult(
            file_path=id_a,
            status=JobStatus.SUCCESS,
            pages=[PageResult(page_num=1, markdown="# Content from Item A", latency=0.2)],
        )
        app._handle_worker_event(
            WorkerEvent(
                WorkerEventType.PAGE_PROGRESS,
                file_path=id_a,
                current_page=1,
                total_pages=1,
                page_result=PageResult(page_num=1, markdown="# Content from Item A"),
            )
        )
        app._handle_worker_event(WorkerEvent(WorkerEventType.COMPLETED, file_path=id_a, result=res_a))

        # Item B must still be selected
        assert app._selected_item_id == id_b

        # Preview must NOT contain item A's content
        raw_text = app._tb_markdown.get("1.0", "end")
        assert "Content from Item A" not in raw_text

        # Now complete item B with its own distinct content
        res_b = OCRResult(
            file_path=id_b,
            status=JobStatus.SUCCESS,
            pages=[PageResult(page_num=1, markdown="# Content from Item B", latency=0.3)],
        )
        app._handle_worker_event(WorkerEvent(WorkerEventType.COMPLETED, file_path=id_b, result=res_b))

        # Active tab ("Raw Markdown") should now have Item B's content
        assert "Content from Item B" in app._tb_markdown.get("1.0", "end")

        # Now switch tabs to "Text Preview" - must render Item B's content on-demand
        app.select_tab("Text Preview")
        assert "Content from Item B" in app._tb_preview.get("1.0", "end")
        assert "Content from Item A" not in app._tb_preview.get("1.0", "end")

        # Switch to "JSON Tree" - must render Item B's JSON on-demand
        app.select_tab("JSON Tree")
        assert "Content from Item B" in app._tb_json.get("1.0", "end")
        assert "Content from Item A" not in app._tb_json.get("1.0", "end")
    finally:
        app._on_closing()


def test_batch3_adaptive_polling_backoff(monkeypatch) -> None:
    """Verify adaptive polling backoff for queue poller, server poller, and status widget caching (P5)."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # 1. Queue Poller Backoff
        # Drain result queue
        while not app._result_queue.empty():
            app._result_queue.get_nowait()

        scheduled_intervals = []
        orig_after = app.after

        def mock_after(ms, func, *args):
            if func == app._process_result_queue:
                scheduled_intervals.append(ms)
                return "mock_timer_id"
            return orig_after(ms, func, *args)

        monkeypatch.setattr(app, "after", mock_after)

        # Case A: Idle (empty task queue, not processing) -> 250ms
        scheduled_intervals.clear()
        app._process_result_queue()
        assert scheduled_intervals[-1] == 250

        # Case B: Pending items in task queue -> 50ms
        app._task_queue.put(Path("test.pdf"))
        scheduled_intervals.clear()
        app._process_result_queue()
        assert scheduled_intervals[-1] == 50

        # Drain task queue
        app._task_queue.get_nowait()

        # Case C: Worker actively processing (cancel event set) -> 50ms
        app._current_cancel_event = threading.Event()
        scheduled_intervals.clear()
        app._process_result_queue()
        assert scheduled_intervals[-1] == 50
        app._current_cancel_event = None

        # 2. Server status update caching (no redundant widget reconfiguration)
        from core.server_manager import ServerStatusInfo, ServerStatus, ServerOwnership
        pill_config_calls = []
        orig_pill_config = app._server_status_pill.configure

        def mock_pill_config(**kwargs):
            pill_config_calls.append(kwargs)
            return orig_pill_config(**kwargs)

        monkeypatch.setattr(app._server_status_pill, "configure", mock_pill_config)

        # First call: applies and configures widget
        pill_config_calls.clear()
        info1 = ServerStatusInfo(status=ServerStatus.READY, ownership=ServerOwnership.MANAGED, message="Running")
        app._apply_server_status_update(info1)
        assert len(pill_config_calls) == 1

        # Second call with identical status & ownership: skips reconfiguration
        pill_config_calls.clear()
        app._apply_server_status_update(info1)
        assert len(pill_config_calls) == 0

        # Third call with changed status: applies reconfiguration
        info2 = ServerStatusInfo(status=ServerStatus.OFFLINE, ownership=ServerOwnership.MANAGED, message="Offline")
        app._apply_server_status_update(info2)
        assert len(pill_config_calls) == 1
    finally:
        app._on_closing()


def test_batch3_batch_folder_drop_and_validation(tmp_path: Path) -> None:
    """Verify background directory scanning, chunked row insertion, and per-file validation (P6)."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        drop_dir = tmp_path / "batch_drop"
        drop_dir.mkdir()

        # Create 30 valid PDFs and 5 unsupported files
        valid_files = []
        for i in range(30):
            p = drop_dir / f"doc_{i:02d}.pdf"
            p.write_bytes(f"%PDF-1.4 dummy {i}".encode("utf-8"))
            valid_files.append(p)

        for i in range(5):
            p = drop_dir / f"ignore_{i}.txt"
            p.write_bytes(b"some text")

        # Enqueue directory
        thread = app.enqueue_file(drop_dir)
        assert thread is not None
        app.wait_for_ingest(timeout=5.0)

        # All 30 valid files must be in queue
        assert len(app._queue_items) == 30
        for p in valid_files:
            assert str(p.resolve()) in app._queue_items

        # Unsupported files must not be in queue
        assert str((drop_dir / "ignore_0.txt").resolve()) not in app._queue_items

        # Verify UI header and footer were updated
        assert app._queue_title.cget("text") == "Queue (30)"
        assert "30" in app._lbl_total_val.cget("text")
        assert app._total_count == 30

        # Re-dropping same folder must not create duplicates
        app.enqueue_file(drop_dir)
        app.wait_for_ingest(timeout=5.0)
        assert len(app._queue_items) == 30
    finally:
        app._on_closing()


def test_batch3_queue_item_cap_cleanup_hint(tmp_path: Path) -> None:
    """Verify soft cleanup prompt appears when finished queue items exceed 100 and clears properly (P7)."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # Initially empty
        assert app._queue_cleanup_hint.winfo_manager() == ""

        # Populate with 101 finished items
        for i in range(101):
            p = tmp_path / f"finished_{i}.pdf"
            p.write_bytes(b"%PDF dummy")
            item = QueueItem(
                item_id=str(p.resolve()),
                file_path=p,
                status=QueueItemStatus.SUCCESS,
                result=OCRResult(file_path=str(p.resolve()), status=JobStatus.SUCCESS),
            )
            app._queue_items[item.item_id] = item

        app._update_queue_header()

        # Verify cleanup prompt is now displayed
        assert app._queue_cleanup_hint.winfo_manager() == "grid"
        assert "101 finished items" in app._queue_cleanup_hint.cget("text")
        assert "Clear Finished" in app._queue_cleanup_hint.cget("text")

        # Clear finished items
        app._on_clear_finished()

        # Verify queue is emptied and hint is hidden
        assert len(app._queue_items) == 0
        assert app._queue_cleanup_hint.winfo_manager() == ""
    finally:
        app._on_closing()


def test_batch3_background_export_all_and_concurrency_lock(tmp_path: Path) -> None:
    """Verify Export All runs on background daemon thread and prevents concurrent duplicate exports (P8)."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # Add 2 completed items
        p1 = tmp_path / "item1.pdf"
        p1.write_bytes(b"%PDF dummy 1")
        res1 = OCRResult(file_path=str(p1.resolve()), status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="Item 1")])

        p2 = tmp_path / "item2.pdf"
        p2.write_bytes(b"%PDF dummy 2")
        res2 = OCRResult(file_path=str(p2.resolve()), status=JobStatus.SUCCESS, pages=[PageResult(page_num=1, markdown="Item 2")])

        app._queue_items[str(p1.resolve())] = QueueItem(item_id=str(p1.resolve()), file_path=p1, status=QueueItemStatus.SUCCESS, result=res1)
        app._queue_items[str(p2.resolve())] = QueueItem(item_id=str(p2.resolve()), file_path=p2, status=QueueItemStatus.SUCCESS, result=res2)
        app._update_action_buttons()

        export_target = tmp_path / "export_out"
        export_target.mkdir()

        export_start_event = threading.Event()
        export_finish_event = threading.Event()

        def slow_save_artifacts(result, **kwargs):
            export_start_event.set()
            export_finish_event.wait(timeout=2.0)
            return [export_target / f"{Path(result.file_path).stem}.md"]

        with patch("gui.app.filedialog.askdirectory", return_value=str(export_target)), \
             patch("gui.app.save_artifacts", side_effect=slow_save_artifacts):

            thread1 = app._on_export_all()
            assert thread1 is not None
            assert thread1.is_alive()
            assert thread1.daemon is True

            # Wait until export worker enters save loop
            assert export_start_event.wait(timeout=1.0) is True

            # Verify exporting lock and UI state
            assert app._is_exporting is True
            assert app._btn_export_all.cget("text") == "Exporting..."
            assert app._btn_export_all.cget("state") == "disabled"

            # Attempt a concurrent second Export All call -> must be rejected
            thread2 = app._on_export_all()
            assert thread2 is None

            # Let export finish
            export_finish_event.set()
            app.wait_for_export(timeout=3.0)

        # After export completion
        assert app._is_exporting is False
        assert "Exported 2 documents" in app._footer_status.cget("text")
    finally:
        app._on_closing()










