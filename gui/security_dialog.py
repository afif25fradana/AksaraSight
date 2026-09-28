"""Modal security confirmation dialog for remote network endpoints."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from gui.theme import (
    COLOR_CANVAS_BG,
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_STATUS_WARNING,
    COLOR_SURFACE_1,
    COLOR_SURFACE_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    apply_window_icon,
)


class SecurityConfirmationDialog(ctk.CTkToplevel):
    """Modal dialog for explicit user acknowledgment of remote data exfiltration."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent)
        self.confirmed = False

        self.title("Security Warning: Remote Endpoints")
        self.geometry("520x330")
        self.minsize(480, 300)
        self.configure(fg_color=COLOR_CANVAS_BG)
        # Bypass CustomTkinter's Windows resizable wrapper which schedules an
        # async titlebar re-withdraw timer (causing withdrawal race conditions).
        super(ctk.CTkToplevel, self).resizable(False, False)
        apply_window_icon(self)

        try:
            self.transient(parent)
            self.grab_set()
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda e: self._on_cancel())
        self._build_ui()

        # Center dialog over parent window if possible
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - 520) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - 330) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

        try:
            self.focus_force()
        except Exception:
            pass

    def _build_ui(self) -> None:
        card = ctk.CTkFrame(
            self,
            fg_color=COLOR_SURFACE_1,
            corner_radius=8,
            border_width=1,
            border_color="#7c4a0a",
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        # Warning Pill Header
        pill = ctk.CTkLabel(
            card,
            text="⚠  DATA EXFILTRATION RISK",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_STATUS_WARNING,
            fg_color="#3d2a00",
            corner_radius=4,
            padx=10,
            pady=4,
        )
        pill.pack(anchor="w", padx=16, pady=(16, 8))

        # Title
        lbl_title = ctk.CTkLabel(
            card,
            text="Enable Remote Network Endpoints?",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        lbl_title.pack(anchor="w", padx=16, pady=(0, 8))

        # Explanation
        lbl_desc = ctk.CTkLabel(
            card,
            text=(
                "Enabling remote network endpoints allows document scan rasters and "
                "extracted OCR text to be transmitted across your local network or the "
                "internet to an external server.\n\n"
                "Confidential document data will leave this physical device. "
                "Only enable this if you control and trust the remote server endpoint."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
            wraplength=450,
        )
        lbl_desc.pack(anchor="w", padx=16, pady=(0, 16))

        # Action Buttons
        btn_frame = ctk.CTkFrame(card, fg_color="transparent", height=1)
        btn_frame.pack(fill="x", padx=16, pady=(0, 16), side="bottom")
        btn_frame.grid_columnconfigure(0, weight=1)

        btn_cancel = ctk.CTkButton(
            btn_frame,
            text="Keep Local Only (Cancel)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            width=160,
            height=32,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            command=self._on_cancel,
        )
        btn_cancel.grid(row=0, column=1, padx=(0, 8))

        btn_confirm = ctk.CTkButton(
            btn_frame,
            text="I Understand, Enable",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=150,
            height=32,
            fg_color="#b45309",
            hover_color="#d97706",
            text_color="#ffffff",
            command=self._on_confirm,
        )
        btn_confirm.grid(row=0, column=2)

    def _on_confirm(self) -> None:
        self.confirmed = True
        self.destroy()

    def _on_cancel(self) -> None:
        self.confirmed = False
        self.destroy()

    @classmethod
    def ask_confirmation(cls, parent: Any) -> bool:
        """Display dialog modally and return True if user confirmed."""
        dialog = cls(parent)
        dialog.wait_window()
        return dialog.confirmed
