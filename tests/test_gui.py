"""Unit and functional tests for gui/app.py."""

from pathlib import Path
import queue
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from core.models import JobStatus, OCRResult, PageResult
from gui.app import OCRApp, WorkerEvent, WorkerEventType


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


def test_app_dnd_drop_handling(tmp_path):
    """Verify _on_drop_files parses space-delimited and braced file lists correctly."""
    mock_engine = MagicMock()
    app = OCRApp(engine=mock_engine)
    app.withdraw()

    try:
        # Multiple dropped paths with spaces
        drop_data = "{C:/Folder Name/invoice 1.pdf} C:/simple.png"
        event = SimpleNamespace(data=drop_data)

        with patch.object(app, "enqueue_file") as mock_enqueue:
            app._on_drop_files(event)

            assert mock_enqueue.call_count == 2
            assert mock_enqueue.call_args_list[0][0][0] == Path("C:/Folder Name/invoice 1.pdf")
            assert mock_enqueue.call_args_list[1][0][0] == Path("C:/simple.png")
    finally:
        app._on_closing()
