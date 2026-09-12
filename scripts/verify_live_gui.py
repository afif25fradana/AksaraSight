"""Verification script running real OCRApp against live llama-server."""

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gui.app import OCRApp, QueueItemStatus
from scripts.capture_gui_screenshot import capture_window_to_image


def main() -> None:
    print("Initializing real OCRApp connected to live llama-server...")
    app = OCRApp()
    app.update()

    pdf_path = Path("sample_contract.pdf").resolve()
    print(f"Enqueuing real file: {pdf_path.name}...")
    app.enqueue_file(pdf_path)

    start = time.time()
    while time.time() - start < 45:
        app.update_idletasks()
        app.update()
        item = app._queue_items.get(str(pdf_path))
        if item and item.status == QueueItemStatus.SUCCESS:
            print(f"Processing complete in {item.duration:.2f}s!")
            break
        time.sleep(0.1)

    # Let UI settle
    time.sleep(0.5)
    app.update_idletasks()
    app.update()

    item = app._queue_items.get(str(pdf_path))
    assert item is not None, "Item missing from queue"
    assert item.status == QueueItemStatus.SUCCESS, f"Expected SUCCESS, got {item.status}"

    md_text = app._tb_markdown.get("1.0", "end").strip()
    json_text = app._tb_json.get("1.0", "end").strip()

    print("\n--- Live GUI State Verification ---")
    print(f"Backend badge: {app._backend_badge.cget('text')}")
    print(f"Status label: {app._status_label.cget('text')}")
    print(f"Counters: Total={app._lbl_total_val.cget('text')}, Success={app._lbl_success_val.cget('text')}, Failed={app._lbl_failed_val.cget('text')}")
    print(f"Markdown preview characters: {len(md_text)}")
    print(f"JSON preview characters: {len(json_text)}")

    print("\n--- Markdown Preview Snippet ---")
    print(md_text[:200])

    # Capture visual screenshot of live working GUI
    out_img = Path("docs/images/gui_live_backend_preview.png")
    out_img.parent.mkdir(parents=True, exist_ok=True)
    img = capture_window_to_image(app)
    img.save(out_img)
    print(f"\nSaved live GUI screenshot to {out_img}")

    app._on_closing()
    print("Application closed cleanly.")


if __name__ == "__main__":
    main()
