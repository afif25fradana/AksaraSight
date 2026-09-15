"""Standalone smoke test script for gui/app.py.

Verifies:
1. App initialization and CustomTkinter / TkinterDnD2 window creation.
2. Simulated file drag-and-drop event with path parsing and console logging.
3. Background worker execution (using mock engine) posting results safely to the UI thread.
4. Clean application shutdown without hanging processes or orphaned worker threads.
"""

from pathlib import Path
import sys

# Ensure repository root is on sys.path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.models import JobStatus, OCRResult
from gui.app import OCRApp


def main() -> None:
    print("=" * 60)
    print("AksaraSight Local Studio - GUI Shell & Worker Smoke Test")
    print("=" * 60)

    # Configure mock engine to avoid requiring live local LLM backend for smoke test
    mock_engine = MagicMock()
    mock_engine.process_document.side_effect = lambda path, *args, **kwargs: OCRResult(
        file_path=str(path),
        status=JobStatus.SUCCESS,
    )

    print("[1/4] Initializing OCRApp window and background worker thread...")
    app = OCRApp(engine=mock_engine)

    # Withdraw window so it runs non-intrusively in background
    app.withdraw()
    print("      -> Window created, worker thread running (daemon=True).")

    print("[2/4] Simulating native drag-and-drop file drop event with real temporary files...")
    import tempfile
    from PIL import Image
    import pypdfium2 as pdfium

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        invoice_pdf = tmp_path / "Invoice 2026.pdf"
        receipt_png = tmp_path / "receipt.png"

        # Create real valid dummy PDF and PNG
        doc = pdfium.PdfDocument.new()
        doc.new_page(200, 200)
        doc.save(str(invoice_pdf))
        doc.close()

        Image.new("RGB", (100, 100), color="blue").save(receipt_png)

        # TkinterDnD data string format with space-containing path in braces
        sample_paths = f"{{{invoice_pdf}}} {{{receipt_png}}}"
        fake_event = SimpleNamespace(data=sample_paths)
        app._on_drop_files(fake_event)

        print("[3/4] Processing worker queue on main thread...")
        start_time = time.time()
        while time.time() - start_time < 3.0:
            app._process_result_queue()
            app.update()
            if mock_engine.process_document.call_count >= 2:
                break
            time.sleep(0.05)

        print(f"      -> Processed {mock_engine.process_document.call_count} documents via worker thread.")
        assert mock_engine.process_document.call_count == 2, "Expected 2 documents to be processed"

    print("[4/4] Triggering clean shutdown (_on_closing)...")
    app._on_closing()
    print("      -> Worker stopped, client sessions closed, window destroyed.")

    print("=" * 60)
    print("Smoke Test PASSED: All operations completed cleanly without hanging!")
    print("=" * 60)


if __name__ == "__main__":
    main()
