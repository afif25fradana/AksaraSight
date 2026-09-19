"""Capture visual screenshot of the SettingsWindow dialog."""

from pathlib import Path
import sys
import time

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import customtkinter as ctk

from config.settings import Settings
from gui.settings_window import SecurityConfirmationDialog, SettingsWindow
from scripts.capture_gui_screenshot import capture_window_to_image


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
        runtime_mode="managed",
        managed_backend_override="auto",
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

    # Scroll down to capture Managed Runtime and Server Supervision
    win._scroll._parent_canvas.yview_moveto(1.0)
    win.update_idletasks()
    win.update()
    time.sleep(0.3)

    img_scrolled = capture_window_to_image(win)
    out_scrolled_path = Path("docs/images/settings_window_scrolled_preview.png").resolve()
    img_scrolled.save(out_scrolled_path, format="PNG")
    print(f"Saved scrolled preview to: {out_scrolled_path} ({img_scrolled.width}x{img_scrolled.height})")

    # Also copy to local generated directory
    artifact_dir = Path("docs/images/_generated")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "settings_window_preview.png"
    img.save(artifact_path, format="PNG")
    artifact_scrolled_path = artifact_dir / "settings_window_scrolled_preview.png"
    img_scrolled.save(artifact_scrolled_path, format="PNG")

    # Capture SecurityConfirmationDialog
    sec_dialog = SecurityConfirmationDialog(win)
    sec_dialog.update_idletasks()
    sec_dialog.update()
    time.sleep(0.3)
    img_sec = capture_window_to_image(sec_dialog)
    out_sec_path = Path("docs/images/security_confirmation_preview.png").resolve()
    img_sec.save(out_sec_path, format="PNG")
    artifact_sec_path = artifact_dir / "security_confirmation_preview.png"
    img_sec.save(artifact_sec_path, format="PNG")
    print(f"Saved security preview to: {out_sec_path} ({img_sec.width}x{img_sec.height})")
    sec_dialog.destroy()

    print(f"Saved generated previews to: {artifact_dir}")

    win.destroy()
    root.destroy()


if __name__ == "__main__":
    main()
