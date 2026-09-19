"""Capture a high-fidelity visual screenshot of the refined AksaraSight Local Studio GUI."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import shutil
import sys
import tempfile
import time
from unittest.mock import MagicMock

# Ensure repository root is on sys.path for direct script execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from config.settings import Settings
from core.models import JobStatus, OCRResult, PageResult
from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo
from gui.app import (
    COLOR_STATUS_FAILED,
    COLOR_STATUS_PROCESSING,
    COLOR_STATUS_QUEUED,
    COLOR_STATUS_SUCCESS,
    OCRApp,
    QueueItemStatus,
)


def capture_window_to_image(app: OCRApp) -> Image.Image:
    """Capture a window HWND using Windows GDI PrintWindow into a PIL Image."""
    app.update_idletasks()
    app.update()

    hwnd = ctypes.windll.user32.GetParent(app.winfo_id()) or app.winfo_id()

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top

    hdc_win = ctypes.windll.user32.GetWindowDC(hwnd)
    hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_win)
    hbm = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    ctypes.windll.gdi32.SelectObject(hdc_mem, hbm)

    # PrintWindow flag 2 = PW_RENDERFULLCONTENT
    ctypes.windll.user32.PrintWindow(hwnd, hdc_mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down DIB
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    ctypes.windll.gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)

    img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)

    ctypes.windll.gdi32.DeleteObject(hbm)
    ctypes.windll.gdi32.DeleteDC(hdc_mem)
    ctypes.windll.user32.ReleaseDC(hwnd, hdc_win)

    return img.convert("RGB")


def main() -> None:
    """Initialize GUI with representative document states and capture visual preview."""
    temp_dir = Path(tempfile.mkdtemp(prefix="aksarasight_preview_"))

    try:
        # Create dummy sample files on disk with realistic sizes
        f_success = temp_dir / "financial_report_2026.pdf"
        f_success.write_bytes(b"x" * (2_400_000))

        f_proc = temp_dir / "scanned_receipt_lunch.png"
        f_proc.write_bytes(b"x" * (450_000))

        f_failed = temp_dir / "corrupt_archive_scan.pdf"
        f_failed.write_bytes(b"x" * (120_000))

        f_queued = temp_dir / "quarterly_presentation.pdf"
        f_queued.write_bytes(b"x" * (5_200_000))

        mock_engine = MagicMock()
        app = OCRApp(settings=Settings(), engine=mock_engine)
        app.geometry("1140x700+20+10")

        # Prevent background worker from consuming demo queue items
        app._task_queue.put = lambda item, *args, **kwargs: None

        # Allow initial empty window to paint and capture empty queue state
        app.update()
        app.update_idletasks()
        time.sleep(0.3)
        app.update()

        out_dir = Path("docs/images")
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir = Path("docs/images/_generated")
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Enqueue sample files
        app.enqueue_file(f_success)
        app.enqueue_file(f_proc)
        app.enqueue_file(f_failed)
        app.enqueue_file(f_queued)

        id_success = str(f_success.resolve())
        id_proc = str(f_proc.resolve())
        id_failed = str(f_failed.resolve())
        id_queued = str(f_queued.resolve())

        # 1. Success item (completed 3-page financial report)
        markdown_body = (
            "# Executive Financial Summary - FY2026\n\n"
            "### Revenue & Profitability Performance\n\n"
            "| Period | Revenue ($M) | Gross Margin | Operating Income |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| Q1 2026 | $124.5M | 68.2% | $34.1M |\n"
            "| Q2 2026 | $138.2M | 70.4% | $41.8M |\n"
            "| Q3 2026 | $145.0M | 71.1% | $46.2M |\n"
            "| Q4 2026 | $162.8M | 72.5% | $52.9M |\n\n"
            "**Total FY2026 Revenue**: **$570.5M** (+24.2% YoY growth).\n\n"
            "### Key Operational Highlights\n"
            "- Enterprise adoption of on-premise local inference accelerated by 42%.\n"
            "- Sub-second OCR latency achieved across dense tabular documents.\n"
            "- Zero data egress maintained with 100% offline edge processing.\n"
        )
        res_success = OCRResult(
            file_path=id_success,
            status=JobStatus.SUCCESS,
            total_duration=1.4,
            pages=[
                PageResult(page_num=1, markdown=markdown_body, latency=0.5),
                PageResult(page_num=2, markdown="## Notes to Financial Statements", latency=0.4),
                PageResult(page_num=3, markdown="## Auditor Certification", latency=0.5),
            ],
        )
        item_success = app._queue_items[id_success]
        item_success.status = QueueItemStatus.SUCCESS
        item_success.duration = 1.4
        item_success.result = res_success
        assert item_success.badge_label is not None and item_success.detail_label is not None
        item_success.badge_label.configure(text="●", text_color=COLOR_STATUS_SUCCESS)
        item_success.detail_label.configure(text=app._format_queue_item_meta(item_success))

        # 2. Processing item
        item_proc = app._queue_items[id_proc]
        item_proc.status = QueueItemStatus.PROCESSING
        assert item_proc.badge_label is not None and item_proc.detail_label is not None
        item_proc.badge_label.configure(text="●", text_color=COLOR_STATUS_PROCESSING)
        item_proc.detail_label.configure(text=app._format_queue_item_meta(item_proc))

        # 3. Failed item
        item_failed = app._queue_items[id_failed]
        item_failed.status = QueueItemStatus.FAILED
        item_failed.error = "Corrupted xref table in document header"
        assert item_failed.badge_label is not None and item_failed.detail_label is not None
        item_failed.badge_label.configure(text="●", text_color=COLOR_STATUS_FAILED)
        item_failed.detail_label.configure(text=app._format_queue_item_meta(item_failed))

        # 4. Queued item
        item_queued = app._queue_items[id_queued]
        item_queued.status = QueueItemStatus.QUEUED
        assert item_queued.badge_label is not None and item_queued.detail_label is not None
        item_queued.badge_label.configure(text="●", text_color=COLOR_STATUS_QUEUED)
        item_queued.detail_label.configure(text=app._format_queue_item_meta(item_queued))

        # Update queue counter header & footer
        app._total_count = 4
        app._success_count = 1
        app._failed_count = 1
        app._update_queue_header()
        app._update_footer("Idle · Ready for documents")

        # Select the success item to display full preview, markdown, JSON, and enabled export buttons
        app._select_queue_item(id_success)
        app.select_tab("Text Preview")

        # Allow layout calculations and animations to stabilize
        app.update()
        app.update_idletasks()
        time.sleep(0.5)
        app.update()

        # Capture screenshot
        img = capture_window_to_image(app)

        # Save to artifacts directory and project docs/images directory
        out_dir = Path("docs/images")
        out_dir.mkdir(parents=True, exist_ok=True)
        local_png = out_dir / "gui_refined_preview.png"
        img.save(local_png)
        print(f"Captured screenshot to: {local_png} (size: {img.size})")

        # Also copy to local generated directory
        artifact_dir = Path("docs/images/_generated")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_png = artifact_dir / "gui_refined_preview.png"
        img.save(artifact_png)
        print(f"Copied screenshot to generated directory: {artifact_png}")

        # Clean shutdown
        app._on_closing()

        # Capture live backend scenario
        capture_live_backend_preview(temp_dir, out_dir, artifact_dir)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def capture_live_backend_preview(temp_dir: Path, out_dir: Path, artifact_dir: Path) -> None:
    """Capture live backend scenario with managed server status and completed contract extraction."""
    f_contract = temp_dir / "sample_contract.pdf"
    f_contract.write_bytes(b"x" * 59_800)

    mock_engine = MagicMock()
    app = OCRApp(settings=Settings(auto_start_server=False), engine=mock_engine)
    app.geometry("1140x700+20+10")
    app._task_queue.put = lambda item, *args, **kwargs: None

    app.enqueue_file(f_contract)
    id_contract = str(f_contract.resolve())

    contract_md = (
        "MASTER SERVICES AGREEMENT\n\n"
        "This Agreement is entered into on September 13, 2026, by and between:\n"
        "Client: Enterprise Global LLC\n"
        "Vendor: AI Local Solutions Inc.\n\n"
        "1. SCOPE OF SERVICES\n"
        "The Vendor shall provide local vision and OCR pipeline development services, including on-device document intelligence and schema extraction.\n\n"
        "2. DELIVERABLES\n"
        "Deliverable 1: Local Vision Inference Client (llama.cpp integration)\n"
        "Deliverable 2: Batch PDF Rasterization Pipeline (pypdfium2)\n"
        "Deliverable 3: Desktop GUI Studio (CustomTkinter)\n\n"
        "[Page 1 of 2]\n\n"
        "---\n\n"
        "3. PAYMENT & FEES\n"
        "The Client agrees to compensate the Vendor within 30 days of invoice delivery. Total Contract Value: $7,500.00 USD.\n\n"
        "4. CONFIDENTIALITY\n"
        "All document data processed locally shall remain strictly on-premise. No telemetry or external network calls are permitted under any circumstances.\n\n"
        "SIGNATURES\n\n"
        "Client Representative: ____________  Date: 2026-09-13\n"
        "Vendor Representative: ____________  Date: 2026-09-13\n\n"
        "[Page 2 of 2]"
    )

    parts = contract_md.split("---")
    res = OCRResult(
        file_path=id_contract,
        status=JobStatus.SUCCESS,
        total_duration=5.2,
        pages=[
            PageResult(page_num=1, markdown=parts[0].strip(), latency=2.6),
            PageResult(page_num=2, markdown=parts[1].strip(), latency=2.6),
        ],
    )
    item = app._queue_items[id_contract]
    item.status = QueueItemStatus.SUCCESS
    item.duration = 5.2
    item.result = res
    assert item.badge_label is not None and item.detail_label is not None
    item.badge_label.configure(text="●", text_color=COLOR_STATUS_SUCCESS)
    item.detail_label.configure(text=app._format_queue_item_meta(item))

    # Configure server status as READY (Managed)
    info = ServerStatusInfo(
        status=ServerStatus.READY,
        ownership=ServerOwnership.MANAGED,
        message="Server is operational and responsive",
        endpoint="http://127.0.0.1:8080/v1",
    )
    app._apply_server_status_update(info)

    # Update queue counter header & footer
    app._total_count = 1
    app._success_count = 1
    app._failed_count = 0
    app._update_queue_header()
    app._update_footer("Done: sample_contract.pdf (SUCCESS)")

    # Select the contract item and activate Raw Markdown tab
    app._select_queue_item(id_contract)
    app.select_tab("Raw Markdown")

    # Allow layout to stabilize
    app.update()
    app.update_idletasks()
    time.sleep(0.5)
    app.update()

    img_live = capture_window_to_image(app)
    out_live = out_dir / "gui_live_backend_preview.png"
    img_live.save(out_live)
    img_live.save(artifact_dir / "gui_live_backend_preview.png")
    print(f"Captured live backend screenshot to: {out_live} (size: {img_live.size})")

    app._on_closing()


if __name__ == "__main__":
    main()
