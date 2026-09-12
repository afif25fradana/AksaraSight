import inspect
import json
from pathlib import Path
import queue
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
import pytest

from core.constants import SUPPORTED_EXTENSIONS
from core.formatter import save_artifacts
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat, PageResult
from gui.app import (
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

        # Select file 1 explicitly
        app._select_queue_item(file1_id)
        assert app._selected_item_id == file1_id

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
        assert item2.badge_label.cget("text") == "[✓]"
        assert "1.5s" in item2.detail_label.cget("text")

        # Now when user selects file 2, preview pane updates to file 2's content
        app._select_queue_item(file2_id)
        assert app._selected_item_id == file2_id
        assert "Page 2 Extracted Heading" in app._tb_preview.get("1.0", "end")
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
        assert "Document Queued: sample.pdf" in app._tb_preview.get("1.0", "end")
        assert '"status": "QUEUED"' in app._tb_json.get("1.0", "end")
        assert app._btn_copy.cget("state") == "disabled"
        assert app._btn_export_selected.cget("state") == "disabled"

        # 2. PROCESSING state
        item.status = QueueItemStatus.PROCESSING
        app._render_preview(item)
        assert "is currently being processed" in app._tb_markdown.get("1.0", "end")
        assert "Processing Document: sample.pdf" in app._tb_preview.get("1.0", "end")
        assert '"status": "PROCESSING"' in app._tb_json.get("1.0", "end")
        assert app._btn_copy.cget("state") == "disabled"
        assert app._btn_export_selected.cget("state") == "disabled"

        # 3. FAILED state
        item.status = QueueItemStatus.FAILED
        item.error = "Connection timeout to local backend"
        app._render_preview(item)
        assert "Error processing sample.pdf" in app._tb_markdown.get("1.0", "end")
        assert "Connection timeout to local backend" in app._tb_preview.get("1.0", "end")
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
