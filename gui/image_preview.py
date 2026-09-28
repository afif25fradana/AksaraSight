"""On-demand document image preview controller for AksaraSight Desktop Studio.

Handles single-page rasterization, Lanczos display downscaling, pagination,
and navigation controls for image preview tab.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import customtkinter as ctk
from PIL import Image

from core.pipeline import PipelineError, rasterize_page
from gui.theme import (
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_SCROLLBAR_THUMB,
    COLOR_SCROLLBAR_THUMB_HOVER,
    COLOR_SURFACE_1,
    COLOR_SURFACE_2,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
)


class ImagePreviewController:
    """Manages on-demand page raster preview, navigation bar, and canvas."""

    def __init__(
        self,
        preview_tab: ctk.CTkFrame,
        settings: Optional[Any] = None,
        navigation_buttons: Optional[Tuple[ctk.CTkButton, ctk.CTkButton]] = None,
        get_current_item: Optional[Callable[[], Optional[Any]]] = None,
    ) -> None:
        self.preview_tab = preview_tab
        self.settings = settings
        self.get_current_item = get_current_item
        self.current_page_idx: int = 0
        self.current_ctk_image: Optional[ctk.CTkImage] = None

        if navigation_buttons is not None:
            self.btn_prev, self.btn_next = navigation_buttons
            self.btn_prev.configure(command=self.on_prev)
            self.btn_next.configure(command=self.on_next)
            self.nav_bar = None
            self.lbl_page = None
            self.lbl_info = None
        else:
            # Navigation Bar
            self.nav_bar = ctk.CTkFrame(preview_tab, fg_color=COLOR_SURFACE_1, height=36, corner_radius=6)
            self.nav_bar.pack(fill="x", padx=4, pady=(4, 6))
            self.nav_bar.grid_columnconfigure(0, weight=0)
            self.nav_bar.grid_columnconfigure(1, weight=0)
            self.nav_bar.grid_columnconfigure(2, weight=0)
            self.nav_bar.grid_columnconfigure(3, weight=1)
            self.nav_bar.grid_columnconfigure(4, weight=0)

            self.btn_prev = ctk.CTkButton(
                self.nav_bar,
                text="◀ Prev",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                width=65,
                height=26,
                fg_color=COLOR_INTERACTIVE_NEUTRAL,
                hover_color=COLOR_INTERACTIVE_HOVER,
                text_color=COLOR_TEXT_PRIMARY,
                state="disabled",
                command=self.on_prev,
            )
            self.btn_prev.grid(row=0, column=0, padx=(6, 4), pady=4)

            self.lbl_page = ctk.CTkLabel(
                self.nav_bar,
                text="Page 0 of 0",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLOR_TEXT_PRIMARY,
            )
            self.lbl_page.grid(row=0, column=1, padx=6, pady=4)

            self.btn_next = ctk.CTkButton(
                self.nav_bar,
                text="Next ▶",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                width=65,
                height=26,
                fg_color=COLOR_INTERACTIVE_NEUTRAL,
                hover_color=COLOR_INTERACTIVE_HOVER,
                text_color=COLOR_TEXT_PRIMARY,
                state="disabled",
                command=self.on_next,
            )
            self.btn_next.grid(row=0, column=2, padx=(4, 6), pady=4)

            self.lbl_info = ctk.CTkLabel(
                self.nav_bar,
                text="",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLOR_TEXT_MUTED,
            )
            self.lbl_info.grid(row=0, column=4, padx=10, pady=4, sticky="e")

        # Scrollable image display frame
        self.scroll_frame = ctk.CTkScrollableFrame(
            preview_tab,
            corner_radius=6,
            fg_color=COLOR_SURFACE_2,
            scrollbar_button_color=COLOR_SCROLLBAR_THUMB,
            scrollbar_button_hover_color=COLOR_SCROLLBAR_THUMB_HOVER,
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self.display_label = ctk.CTkLabel(
            self.scroll_frame,
            text="No image preview available for this document.\nProcess a document to inspect scan raster.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        self.display_label.pack(expand=True, pady=40)

    def load_page(
        self,
        file_path: Path,
        page_index: int = 0,
        effective_dpi: Optional[int] = None,
    ) -> Tuple[Optional[Image.Image], Optional[str]]:
        """Load and rasterize a single page on-demand from disk.

        Returns:
            Tuple[Optional[Image.Image], Optional[str]]: (PIL image, error message).
        """
        if not file_path.is_file():
            return None, f"Source file unavailable:\n{file_path.name}\n\n(File was moved or deleted after enqueue)"

        if effective_dpi is None:
            effective_dpi = getattr(self.settings, "dpi", 100) or 100

        try:
            raw_bytes = rasterize_page(file_path, page_idx=page_index, dpi=effective_dpi)
            pil_img = Image.open(io.BytesIO(raw_bytes))
            pil_img.load()
            return pil_img, None
        except PipelineError as exc:
            return None, f"Failed to load image preview: {exc}"
        except Exception as exc:
            return None, f"Failed to load image preview: {exc}"

    def render(self, item: Any) -> None:
        """Render original raster scan image for the active document page on-demand."""
        if not (item and item.result and item.result.pages):
            self.reset()
            return

        total_img_pages = len(item.result.pages)
        if total_img_pages == 0:
            self.reset()
            return

        self.current_page_idx = max(0, min(self.current_page_idx, total_img_pages - 1))
        target_page = item.result.pages[self.current_page_idx]

        dpi_val = getattr(item, "processed_dpi", None) or getattr(self.settings, "dpi", 100) or 100
        pil_img, err_msg = self.load_page(
            item.file_path,
            page_index=self.current_page_idx,
            effective_dpi=dpi_val,
        )

        if err_msg or pil_img is None:
            self.current_ctk_image = None
            self.display_label.configure(
                image="",
                text=err_msg or "Failed to load image preview",
            )
            if self.lbl_page:
                self.lbl_page.configure(text=f"Page {self.current_page_idx + 1} of {total_img_pages}")
            if self.lbl_info:
                self.lbl_info.configure(text="")
            if self.btn_prev:
                self.btn_prev.configure(state="normal" if self.current_page_idx > 0 else "disabled")
            if self.btn_next:
                self.btn_next.configure(state="normal" if self.current_page_idx < total_img_pages - 1 else "disabled")
            return

        try:
            if pil_img.mode not in ("RGB", "RGBA"):
                pil_img = pil_img.convert("RGB")

            orig_w, orig_h = pil_img.size
            max_w, max_h = 620, 750
            scale = min(max_w / orig_w, max_h / orig_h, 1.0)
            disp_w = max(1, int(orig_w * scale))
            disp_h = max(1, int(orig_h * scale))

            scaled_img = pil_img.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=scaled_img, dark_image=scaled_img, size=(disp_w, disp_h))
            self.current_ctk_image = ctk_img

            self.display_label.configure(image=ctk_img, text="")
            if self.lbl_page:
                self.lbl_page.configure(text=f"Page {self.current_page_idx + 1} of {total_img_pages}")
            info_txt = f"{orig_w} × {orig_h} px @ {dpi_val} DPI"
            if target_page.truncated:
                info_txt += " · ⚠ Truncated"
            if self.lbl_info:
                self.lbl_info.configure(text=info_txt)
            if self.btn_prev:
                self.btn_prev.configure(state="normal" if self.current_page_idx > 0 else "disabled")
            if self.btn_next:
                self.btn_next.configure(state="normal" if self.current_page_idx < total_img_pages - 1 else "disabled")
        except Exception as exc:
            self.current_ctk_image = None
            self.display_label.configure(
                image="",
                text=f"Failed to display image raster: {exc}",
            )
            if self.lbl_page:
                self.lbl_page.configure(text="Page Error")
            if self.lbl_info:
                self.lbl_info.configure(text="")
            if self.btn_prev:
                self.btn_prev.configure(state="disabled")
            if self.btn_next:
                self.btn_next.configure(state="disabled")

    def reset(self) -> None:
        """Reset the image preview controls and canvas to empty state."""
        self.current_page_idx = 0
        self.current_ctk_image = None
        self.display_label.configure(
            image="",
            text="No image preview available for this document.\nProcess a document to inspect scan raster.",
        )
        if self.lbl_page:
            self.lbl_page.configure(text="Page 0 of 0")
        if self.lbl_info:
            self.lbl_info.configure(text="")
        if self.btn_prev:
            self.btn_prev.configure(state="disabled")
        if self.btn_next:
            self.btn_next.configure(state="disabled")

    def on_prev(self, item: Optional[Any] = None) -> None:
        """Navigate to the previous page in Image Preview."""
        if self.current_page_idx > 0:
            self.current_page_idx -= 1
            cur_item = item or (self.get_current_item() if self.get_current_item else None)
            if cur_item:
                self.render(cur_item)

    def on_next(self, item: Optional[Any] = None) -> None:
        """Navigate to the next page in Image Preview."""
        cur_item = item or (self.get_current_item() if self.get_current_item else None)
        if cur_item:
            total_pages = len(cur_item.result.pages) if cur_item.result and cur_item.result.pages else 0
            if self.current_page_idx < total_pages - 1:
                self.current_page_idx += 1
                self.render(cur_item)
