"""Capture visual screenshot of the SettingsWindow dialog."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import customtkinter as ctk

from config.settings import Settings
from gui.settings_window import SettingsWindow


def capture_window_to_image(window) -> Image.Image:
    """Capture a window HWND using Windows GDI PrintWindow into a PIL Image."""
    window.update_idletasks()
    window.update()
    time.sleep(0.3)
    window.update_idletasks()
    window.update()

    hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()

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

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)

    ctypes.windll.gdi32.DeleteObject(hbm)
    ctypes.windll.gdi32.DeleteDC(hdc_mem)
    ctypes.windll.user32.ReleaseDC(hwnd, hdc_win)

    return img.convert("RGB")


def main() -> None:
    root = ctk.CTk()
    root.withdraw()

    # Configure representative settings
    settings = Settings(
        backend="llama-cpp",
        local_endpoint="http://127.0.0.1:8080/v1",
        timeout=60.0,
        max_retries=2,
        allow_remote=False,
        llama_server_path=r"C:\bin\llama-server.exe",
        model_repo="ggml-org/GLM-Edge-V-5B-GGUF",
        auto_start_server=False,
        dpi=100,
        max_pages=None,
    )

    win = SettingsWindow(root, settings=settings)
    win.geometry("640x760+100+100")
    win.update_idletasks()
    win.update()

    img = capture_window_to_image(win)

    out_path = Path("docs/images/settings_window_preview.png").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    print(f"Saved preview to: {out_path} ({img.width}x{img.height})")

    # Also copy to artifacts directory
    artifact_dir = Path(r"docs/images/_generated")
    if artifact_dir.exists():
        artifact_path = artifact_dir / "settings_window_preview.png"
        img.save(artifact_path, format="PNG")
        print(f"Saved artifact preview to: {artifact_path}")

    win.destroy()
    root.destroy()


if __name__ == "__main__":
    main()
