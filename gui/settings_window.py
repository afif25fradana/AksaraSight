"""Preferences and runtime settings modal window for GLM-OCR Local Desktop Studio."""

import logging
from pathlib import Path
import threading
from tkinter import filedialog
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

import customtkinter as ctk

from config.settings import Settings
from core.hardware import (
    HardwareProfile,
    PINNED_LLAMA_BUILD,
    get_cached_hardware_profile,
)
from core.runtime_manager import (
    ensure_runtime,
    get_installed_runtime_path,
    is_runtime_installed,
)

logger = logging.getLogger(__name__)

from gui.theme import (
    COLOR_ACCENT_HOVER,
    COLOR_ACCENT_PRIMARY,
    COLOR_CANVAS_BG,
    COLOR_INTERACTIVE_HOVER,
    COLOR_INTERACTIVE_NEUTRAL,
    COLOR_STATUS_ERROR,
    COLOR_STATUS_SUCCESS,
    COLOR_STATUS_WARNING,
    COLOR_SURFACE_1,
    COLOR_SURFACE_2,
    COLOR_SURFACE_BORDER,
    COLOR_SURFACE_BORDER_HOVER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_TEXT_SUBTLE,
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
        self.resizable(False, False)

        try:
            self.transient(parent)
            self.grab_set()
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._build_ui()

        # Center dialog over parent window if possible
        self.update_idletasks()
        try:
            px = parent.winfo_rootx() + (parent.winfo_width() - 520) // 2
            py = parent.winfo_rooty() + (parent.winfo_height() - 330) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
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


class SettingsWindow(ctk.CTkToplevel):
    """Preferences and Serving Configuration modal dialog.

    Provides a centralized settings management panel with:
    - Live validation enforcing Settings.__post_init__ constraints.
    - Explicit security confirmation on enabling non-loopback connections.
    - Dynamic 'Restart Required' warnings for managed server changes.
    - User-friendly guidance on LLM vision trade-offs (e.g. DPI vs latency).
    """

    def __init__(
        self,
        parent: Any,
        settings: Settings,
        server_manager: Optional[Any] = None,
        on_save_callback: Optional[Callable[[Settings], None]] = None,
    ) -> None:
        """Initialize the Settings modal dialog.

        Args:
            parent: Parent Tk/CTk window.
            settings: Active application Settings instance.
            server_manager: Optional ServerManager instance to inspect managed process status.
            on_save_callback: Callback invoked with the validated Settings upon successful save.
        """
        super().__init__(parent)

        self.parent = parent
        self.settings = settings
        self.server_manager = server_manager
        self.on_save_callback = on_save_callback

        # Hardware profile and download state
        self._hardware_profile = get_cached_hardware_profile()
        self._is_downloading: bool = False
        self._is_closed: bool = False
        self._download_thread: Optional[threading.Thread] = None

        parent_thread = getattr(self.parent, "_runtime_download_thread", None)
        if parent_thread is not None and parent_thread.is_alive():
            self._is_downloading = True
            self._download_thread = parent_thread

        # Track initial server configuration to detect if restart is required
        self._initial_server_config: Tuple[str, str, str] = (
            str(self.settings.effective_llama_server_path or ""),
            str(self.settings.model_repo),
            str(self.settings.local_endpoint),
        )

        # Modal window properties
        self.title("Preferences & Serving Configuration")
        self.geometry("640x740")
        self.minsize(560, 560)
        self.configure(fg_color=COLOR_CANVAS_BG)

        # Position dialog over parent window
        try:
            self.transient(parent)
            self.grab_set()
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._build_ui()
        self._populate_fields(self.settings)

    def _build_ui(self) -> None:
        """Construct the settings window layout and input components."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header
        self.grid_rowconfigure(1, weight=1)  # Scrollable Content
        self.grid_rowconfigure(2, weight=0)  # Banners & Actions

        # ----------------------------------------------------------------------
        # Header Bar
        # ----------------------------------------------------------------------
        header_frame = ctk.CTkFrame(self, fg_color=COLOR_SURFACE_1, corner_radius=0)
        header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 10))
        header_frame.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            header_frame,
            text="Preferences",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        title_label.grid(row=0, column=0, sticky="w", padx=20, pady=(12, 2))

        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="Configure local inference backends, OCR quality, and server lifecycle.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        subtitle_label.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        # ----------------------------------------------------------------------
        # Scrollable Form Body
        # ----------------------------------------------------------------------
        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=COLOR_INTERACTIVE_NEUTRAL,
            scrollbar_button_hover_color=COLOR_INTERACTIVE_HOVER,
        )
        self._scroll.grid(row=1, column=0, sticky="nsew", padx=16, pady=0)
        self._scroll.grid_columnconfigure(0, weight=1)

        row_idx = 0

        # SECTION 1: Local Inference Engine
        sec1 = self._create_section(self._scroll, "Local Inference Engine", row_idx)
        row_idx += 1
        self._build_engine_section(sec1)

        # SECTION 2: OCR Quality & Limits
        sec2 = self._create_section(self._scroll, "OCR Quality & Document Limits", row_idx)
        row_idx += 1
        self._build_quality_section(sec2)

        # SECTION 3: Server Supervision (llama-server)
        sec3 = self._create_section(self._scroll, "Backend Server Supervision", row_idx)
        row_idx += 1
        self._build_server_section(sec3)

        # ----------------------------------------------------------------------
        # Bottom Banners and Action Buttons
        # ----------------------------------------------------------------------
        bottom_container = ctk.CTkFrame(self, fg_color=COLOR_SURFACE_1, corner_radius=0, height=1)
        bottom_container.grid(row=2, column=0, sticky="ew", padx=0, pady=(10, 0))
        bottom_container.grid_columnconfigure(0, weight=1)

        # Warning & Error Banners (packed dynamically only when active)
        self._banner_frame = ctk.CTkFrame(bottom_container, fg_color="transparent", height=1)

        self._lbl_restart_banner = ctk.CTkLabel(
            self._banner_frame,
            text="⚠ Restart Required: Server configuration changes will take effect after you Stop and Start the server.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_STATUS_WARNING,
            fg_color="#3d2a00",
            corner_radius=4,
            padx=10,
            pady=4,
        )

        self._lbl_error_banner = ctk.CTkLabel(
            self._banner_frame,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_STATUS_ERROR,
            fg_color="#3d1419",
            corner_radius=4,
            padx=10,
            pady=4,
            wraplength=580,
            justify="left",
        )

        # Button Bar
        action_bar = ctk.CTkFrame(bottom_container, fg_color="transparent", height=1)
        action_bar.pack(fill="x", padx=16, pady=12)
        self._action_bar = action_bar
        action_bar.grid_columnconfigure(0, weight=1)
        action_bar.grid_columnconfigure(1, weight=0)
        action_bar.grid_columnconfigure(2, weight=0)

        self._btn_cancel = ctk.CTkButton(
            action_bar,
            text="Cancel",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            width=90,
            height=32,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            command=self._on_cancel,
        )
        self._btn_cancel.grid(row=0, column=1, padx=(0, 8))

        self._btn_save = ctk.CTkButton(
            action_bar,
            text="Save Settings",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=110,
            height=32,
            fg_color=COLOR_ACCENT_PRIMARY,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#ffffff",
            command=self._on_save,
        )
        self._btn_save.grid(row=0, column=2)

    def _create_section(self, parent: Any, title: str, grid_row: int) -> ctk.CTkFrame:
        """Create a styled card frame container for a configuration category."""
        frame = ctk.CTkFrame(
            parent,
            fg_color=COLOR_SURFACE_1,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            corner_radius=8,
        )
        frame.grid(row=grid_row, column=0, sticky="ew", padx=4, pady=(0, 12))
        frame.grid_columnconfigure(0, weight=1)

        sec_title = ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
        )
        sec_title.pack(anchor="w", padx=16, pady=(12, 6))

        divider = ctk.CTkFrame(frame, height=1, fg_color=COLOR_SURFACE_BORDER)
        divider.pack(fill="x", padx=16, pady=(0, 10))

        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        content.grid_columnconfigure(0, weight=0, minsize=140)
        content.grid_columnconfigure(1, weight=1)

        return content

    # ==========================================================================
    # Section Builders
    # ==========================================================================

    def _build_engine_section(self, container: ctk.CTkFrame) -> None:
        """Build form inputs for backend selection, endpoint URL, and timeouts."""
        # 1. Backend selector
        lbl_backend = ctk.CTkLabel(
            container,
            text="Backend Engine:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_backend.grid(row=0, column=0, sticky="w", pady=6)

        self._seg_backend = ctk.CTkSegmentedButton(
            container,
            values=["llama-cpp", "ollama", "vllm"],
            selected_color=COLOR_ACCENT_PRIMARY,
            selected_hover_color=COLOR_ACCENT_HOVER,
            unselected_color=COLOR_SURFACE_2,
            unselected_hover_color=COLOR_INTERACTIVE_HOVER,
            font=ctk.CTkFont(family="Segoe UI", size=11),
        )
        self._seg_backend.grid(row=0, column=1, sticky="w", pady=6)

        # 2. Local Endpoint URL
        lbl_ep = ctk.CTkLabel(
            container,
            text="Endpoint URL:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_ep.grid(row=1, column=0, sticky="w", pady=6)

        self._ent_endpoint = ctk.CTkEntry(
            container,
            placeholder_text="http://localhost:8080/v1",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLOR_SURFACE_2,
            border_color=COLOR_SURFACE_BORDER,
        )
        self._ent_endpoint.grid(row=1, column=1, sticky="ew", pady=6)

        # 3. Allow Remote Switch with explicit security confirmation step
        lbl_remote = ctk.CTkLabel(
            container,
            text="Remote Endpoints:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_remote.grid(row=2, column=0, sticky="w", pady=6)

        remote_box = ctk.CTkFrame(container, fg_color="transparent")
        remote_box.grid(row=2, column=1, sticky="w", pady=6)

        self._sw_allow_remote = ctk.CTkSwitch(
            remote_box,
            text="Allow non-loopback / remote network endpoints",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            progress_color=COLOR_STATUS_WARNING,
            command=self._on_toggle_allow_remote,
        )
        self._sw_allow_remote.pack(side="left")

        # 4. Timeout
        lbl_timeout = ctk.CTkLabel(
            container,
            text="Timeout (seconds):",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_timeout.grid(row=3, column=0, sticky="w", pady=6)

        self._ent_timeout = ctk.CTkEntry(
            container,
            placeholder_text="60.0",
            width=100,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_2,
            border_color=COLOR_SURFACE_BORDER,
        )
        self._ent_timeout.grid(row=3, column=1, sticky="w", pady=6)

        # 5. Max Retries
        lbl_retries = ctk.CTkLabel(
            container,
            text="Max Retries:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_retries.grid(row=4, column=0, sticky="w", pady=6)

        self._ent_retries = ctk.CTkEntry(
            container,
            placeholder_text="2",
            width=100,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_2,
            border_color=COLOR_SURFACE_BORDER,
        )
        self._ent_retries.grid(row=4, column=1, sticky="w", pady=6)

    def _build_quality_section(self, container: ctk.CTkFrame) -> None:
        """Build form inputs for DPI and page limits with detailed why explanations."""
        # 1. DPI Slider & Entry
        lbl_dpi = ctk.CTkLabel(
            container,
            text="Raster DPI:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_dpi.grid(row=0, column=0, sticky="w", pady=(6, 2))

        dpi_row = ctk.CTkFrame(container, fg_color="transparent")
        dpi_row.grid(row=0, column=1, sticky="ew", pady=(6, 2))
        dpi_row.grid_columnconfigure(0, weight=1)

        self._slider_dpi = ctk.CTkSlider(
            dpi_row,
            from_=72,
            to=200,
            number_of_steps=128,
            progress_color=COLOR_ACCENT_PRIMARY,
            command=self._on_slider_dpi_changed,
        )
        self._slider_dpi.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self._lbl_dpi_val = ctk.CTkLabel(
            dpi_row,
            text="100 DPI",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            width=60,
        )
        self._lbl_dpi_val.grid(row=0, column=1, sticky="e")

        # DPI Explanation Card
        dpi_card = ctk.CTkFrame(container, fg_color=COLOR_SURFACE_2, corner_radius=6)
        dpi_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10))

        dpi_hint = ctk.CTkLabel(
            dpi_card,
            text=(
                "Recommended: 100 DPI. GLM-OCR vision tokens scale quadratically with raster area.\n"
                "• 150 DPI produces ~4,061 tokens (~5.6s/page)\n"
                "• 100 DPI produces ~2,211 tokens (~2.7s/page) with full character fidelity\n"
                "• 72 DPI is faster (~1.5s/page) but distorts small-text characters ('Tkinler')"
            ),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
            padx=10,
            pady=8,
        )
        dpi_hint.pack(anchor="w")

        # 2. Max Pages
        lbl_max_pages = ctk.CTkLabel(
            container,
            text="Max Pages:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_max_pages.grid(row=2, column=0, sticky="w", pady=6)

        mp_box = ctk.CTkFrame(container, fg_color="transparent")
        mp_box.grid(row=2, column=1, sticky="w", pady=6)

        self._ent_max_pages = ctk.CTkEntry(
            mp_box,
            placeholder_text="All pages",
            width=100,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLOR_SURFACE_2,
            border_color=COLOR_SURFACE_BORDER,
        )
        self._ent_max_pages.pack(side="left")

        lbl_mp_hint = ctk.CTkLabel(
            mp_box,
            text="(Leave empty for all pages)",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_SUBTLE,
        )
        lbl_mp_hint.pack(side="left", padx=(10, 0))

    def _build_server_section(self, container: ctk.CTkFrame) -> None:
        """Build form inputs for runtime source (managed/custom), server path, model repository, and auto-start."""
        # 1. Runtime Source Toggle (Managed vs Custom Path)
        lbl_source = ctk.CTkLabel(
            container,
            text="Runtime Source:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_source.grid(row=0, column=0, sticky="w", pady=6)

        self._seg_runtime_mode = ctk.CTkSegmentedButton(
            container,
            values=["Managed (Auto)", "Custom Path"],
            selected_color=COLOR_ACCENT_PRIMARY,
            selected_hover_color=COLOR_ACCENT_HOVER,
            unselected_color=COLOR_SURFACE_2,
            unselected_hover_color=COLOR_INTERACTIVE_HOVER,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            command=self._on_runtime_mode_changed,
        )
        self._seg_runtime_mode.grid(row=0, column=1, sticky="w", pady=6)

        # Container for runtime views
        self._runtime_container = ctk.CTkFrame(container, fg_color="transparent")
        self._runtime_container.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        self._runtime_container.grid_columnconfigure(0, weight=1)

        # ---------------- Managed Runtime Frame ----------------
        self._frame_managed = ctk.CTkFrame(
            self._runtime_container,
            fg_color=COLOR_SURFACE_2,
            corner_radius=6,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
        )
        self._frame_managed.grid_columnconfigure(1, weight=1)

        # Hardware readout
        hw_title_box = ctk.CTkFrame(self._frame_managed, fg_color="transparent")
        hw_title_box.grid(row=0, column=0, sticky="nw", padx=10, pady=(8, 2))

        lbl_hw_title = ctk.CTkLabel(
            hw_title_box,
            text="Detected Hardware:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_hw_title.pack(anchor="w")

        self._btn_refresh_hw = ctk.CTkButton(
            hw_title_box,
            text="Refresh",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            width=54,
            height=20,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            command=self._on_refresh_hardware,
        )
        self._btn_refresh_hw.pack(anchor="w", pady=(2, 0))

        hw_desc = self._format_hardware_description(self._hardware_profile)
        self._lbl_hw_desc = ctk.CTkLabel(
            self._frame_managed,
            text=hw_desc,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            justify="left",
            anchor="w",
        )
        self._lbl_hw_desc.grid(row=0, column=1, sticky="w", padx=10, pady=(8, 2))

        # Target Backend Override
        lbl_target_backend = ctk.CTkLabel(
            self._frame_managed,
            text="Target Backend:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_target_backend.grid(row=1, column=0, sticky="w", padx=10, pady=4)

        self._seg_managed_backend = ctk.CTkSegmentedButton(
            self._frame_managed,
            values=["auto", "cuda", "vulkan", "cpu"],
            selected_color=COLOR_ACCENT_PRIMARY,
            selected_hover_color=COLOR_ACCENT_HOVER,
            unselected_color=COLOR_SURFACE_1,
            unselected_hover_color=COLOR_INTERACTIVE_HOVER,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            command=self._on_managed_backend_changed,
        )
        self._seg_managed_backend.grid(row=1, column=1, sticky="w", padx=10, pady=4)

        # Installation Status
        lbl_status_title = ctk.CTkLabel(
            self._frame_managed,
            text="Status:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_status_title.grid(row=2, column=0, sticky="w", padx=10, pady=4)

        status_box = ctk.CTkFrame(self._frame_managed, fg_color="transparent")
        status_box.grid(row=2, column=1, sticky="ew", padx=10, pady=4)
        status_box.grid_columnconfigure(0, weight=1)

        self._lbl_managed_status = ctk.CTkLabel(
            status_box,
            text="● Not Installed",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._lbl_managed_status.grid(row=0, column=0, sticky="w")

        self._lbl_managed_path = ctk.CTkLabel(
            status_box,
            text="",
            font=ctk.CTkFont(family="Consolas", size=9),
            text_color=COLOR_TEXT_SUBTLE,
            anchor="w",
        )
        self._lbl_managed_path.grid(row=1, column=0, sticky="w")

        # Download Action & Progress Row
        action_row = ctk.CTkFrame(self._frame_managed, fg_color="transparent")
        action_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 6))
        action_row.grid_columnconfigure(1, weight=1)

        self._btn_download = ctk.CTkButton(
            action_row,
            text="Download Runtime",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            width=140,
            height=28,
            fg_color=COLOR_ACCENT_PRIMARY,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="#ffffff",
            command=self._on_download_runtime,
        )
        self._btn_download.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self._lbl_download_status = ctk.CTkLabel(
            action_row,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._lbl_download_status.grid(row=0, column=1, sticky="w")

        self._progress_download = ctk.CTkProgressBar(
            self._frame_managed,
            progress_color=COLOR_ACCENT_PRIMARY,
            height=6,
        )
        self._progress_download.set(0.0)

        # ---------------- Custom Path Frame ----------------
        self._frame_custom = ctk.CTkFrame(self._runtime_container, fg_color="transparent")
        self._frame_custom.grid_columnconfigure(1, weight=1)

        lbl_path = ctk.CTkLabel(
            self._frame_custom,
            text="llama-server.exe:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_path.grid(row=0, column=0, sticky="w", pady=4)

        path_box = ctk.CTkFrame(self._frame_custom, fg_color="transparent")
        path_box.grid(row=0, column=1, sticky="ew", pady=4)
        path_box.grid_columnconfigure(0, weight=1)

        self._ent_server_path = ctk.CTkEntry(
            path_box,
            placeholder_text=r"C:\tools\llama-cpp\llama-server.exe",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLOR_SURFACE_2,
            border_color=COLOR_SURFACE_BORDER,
        )
        self._ent_server_path.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._btn_browse = ctk.CTkButton(
            path_box,
            text="Browse...",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            width=80,
            height=28,
            fg_color=COLOR_INTERACTIVE_NEUTRAL,
            hover_color=COLOR_INTERACTIVE_HOVER,
            text_color=COLOR_TEXT_PRIMARY,
            border_width=1,
            border_color=COLOR_SURFACE_BORDER,
            command=self._on_browse_server_path,
        )
        self._btn_browse.grid(row=0, column=1)

        # 2. Model Repo
        lbl_repo = ctk.CTkLabel(
            container,
            text="Model Repository:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_repo.grid(row=2, column=0, sticky="w", pady=6)

        self._ent_model_repo = ctk.CTkEntry(
            container,
            placeholder_text="ggml-org/GLM-OCR-GGUF",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLOR_SURFACE_2,
            border_color=COLOR_SURFACE_BORDER,
        )
        self._ent_model_repo.grid(row=2, column=1, sticky="ew", pady=6)

        # 3. Auto-start Server Switch (strictly default False / opt-in)
        lbl_auto = ctk.CTkLabel(
            container,
            text="Auto-Start Server:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_PRIMARY,
            anchor="w",
        )
        lbl_auto.grid(row=3, column=0, sticky="w", pady=6)

        auto_box = ctk.CTkFrame(container, fg_color="transparent")
        auto_box.grid(row=3, column=1, sticky="w", pady=6)

        self._sw_auto_start = ctk.CTkSwitch(
            auto_box,
            text="Launch backend server on app startup if offline (Opt-in)",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            progress_color=COLOR_ACCENT_PRIMARY,
        )
        self._sw_auto_start.pack(side="left")

    # ==========================================================================
    # State Population & Interaction Handlers
    # ==========================================================================

    def _on_runtime_mode_changed(self, mode: str) -> None:
        """Toggle between Managed and Custom Path runtime views."""
        if "Managed" in mode:
            self._frame_custom.pack_forget()
            self._frame_managed.pack(fill="x", expand=True)
            self._update_managed_status()
        else:
            self._frame_managed.pack_forget()
            self._frame_custom.pack(fill="x", expand=True)

    def _on_managed_backend_changed(self, backend: str) -> None:
        """Update installation status display when target backend override is changed."""
        self._update_managed_status(backend)

    def _get_active_target_backend(self) -> str:
        """Resolve the effective backend target name (e.g. 'cuda', 'vulkan', 'cpu')."""
        override = self._seg_managed_backend.get().strip().lower()
        if override == "auto":
            return self._hardware_profile.recommended_backend
        return override

    def _format_hardware_description(self, hw: HardwareProfile) -> str:
        """Format a human-readable summary of detected hardware."""
        if hw.gpu_name:
            vram_str = f" ({hw.vram_mb / 1024:.1f} GB VRAM)" if hw.vram_mb else ""
            driver_str = f" [Driver {hw.cuda_driver_version}]" if hw.cuda_driver_version else ""
            return f"{hw.gpu_name}{vram_str}{driver_str}\nRecommended Backend: {hw.recommended_backend.upper()}"
        cpu_model = hw.cpu_name or "Generic x86_64"
        return f"CPU ({cpu_model})\nRecommended Backend: CPU"

    def _on_refresh_hardware(self) -> None:
        """Force-refresh hardware detection cache and update UI readout."""
        self._hardware_profile = get_cached_hardware_profile(force_refresh=True)
        if hasattr(self, "_lbl_hw_desc"):
            self._lbl_hw_desc.configure(text=self._format_hardware_description(self._hardware_profile))
        self._update_managed_status()

    def _update_managed_status(self, backend: Optional[str] = None) -> None:
        """Refresh the installation status badge, path label, and download button state."""
        target = backend or self._get_active_target_backend()
        if target == "auto":
            target = self._hardware_profile.recommended_backend

        installed = is_runtime_installed(tag=PINNED_LLAMA_BUILD, backend=target)
        if installed:
            path = get_installed_runtime_path(tag=PINNED_LLAMA_BUILD, backend=target)
            self._lbl_managed_status.configure(
                text=f"● Installed ({PINNED_LLAMA_BUILD} - {target})",
                text_color=COLOR_STATUS_SUCCESS,
            )
            if hasattr(self, "_lbl_managed_path"):
                self._lbl_managed_path.configure(text=str(path) if path else "")
            if not self._is_downloading:
                self._btn_download.configure(text="Reinstall / Update", state="normal")
        else:
            self._lbl_managed_status.configure(
                text="● Not Installed",
                text_color=COLOR_TEXT_MUTED,
            )
            if hasattr(self, "_lbl_managed_path"):
                self._lbl_managed_path.configure(text="")
            if not self._is_downloading:
                self._btn_download.configure(text="Download Runtime", state="normal")

    def _safe_ui_dispatch(self, fn: Callable[[], Any]) -> None:
        """Schedule a UI update callback on the Tk event loop only if this window is still open."""
        if getattr(self, "_is_closed", False):
            return
        try:
            self.after(0, fn)
        except Exception:
            pass

    def wait_for_download(self, timeout: float = 5.0) -> None:
        """Wait for active background download thread to complete and flush UI callbacks."""
        if self._download_thread and self._download_thread.is_alive():
            self._download_thread.join(timeout=timeout)
        try:
            self.update_idletasks()
            self.update()
        except Exception:
            pass

    def _on_download_runtime(self) -> None:
        """Download and verify the selected llama.cpp runtime binary asynchronously."""
        # 1. Concurrency guard (mirroring Batch 3 P8 Export All)
        if self._is_downloading:
            return
        if self._download_thread is not None and self._download_thread.is_alive():
            return
        if hasattr(self.parent, "_runtime_download_thread"):
            parent_thread = getattr(self.parent, "_runtime_download_thread")
            if parent_thread is not None and parent_thread.is_alive():
                return

        target_backend = self._get_active_target_backend()
        resolved_target = target_backend if target_backend != "auto" else self._hardware_profile.recommended_backend
        force_download = is_runtime_installed(tag=PINNED_LLAMA_BUILD, backend=resolved_target)

        self._is_downloading = True
        self._btn_download.configure(text="Downloading...", state="disabled")
        self._lbl_download_status.configure(text="Initializing download...", text_color=COLOR_TEXT_MUTED)
        self._progress_download.set(0.0)
        self._progress_download.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))

        def _worker() -> None:
            try:
                def _progress_cb(stage: str, done: int, total: int) -> None:
                    msg = stage
                    frac = 0.0
                    if total > 0:
                        frac = done / total
                        mb_done = done / (1024 * 1024)
                        mb_total = total / (1024 * 1024)
                        msg = f"{stage} ({mb_done:.1f}/{mb_total:.1f} MB)"

                    def _update_ui() -> None:
                        if getattr(self, "_is_closed", False):
                            return
                        try:
                            if hasattr(self, "_lbl_download_status"):
                                self._lbl_download_status.configure(text=msg, text_color=COLOR_TEXT_MUTED)
                            if hasattr(self, "_progress_download") and total > 0:
                                self._progress_download.set(frac)
                        except Exception:
                            pass

                    self._safe_ui_dispatch(_update_ui)

                installed_path = ensure_runtime(
                    backend=target_backend,
                    tag=PINNED_LLAMA_BUILD,
                    progress_callback=_progress_cb,
                    force=force_download,
                )

                def _success_ui() -> None:
                    if getattr(self, "_is_closed", False):
                        return
                    try:
                        if hasattr(self, "_progress_download"):
                            self._progress_download.set(1.0)
                        if hasattr(self, "_lbl_download_status"):
                            self._lbl_download_status.configure(
                                text=f"Runtime ready ({PINNED_LLAMA_BUILD})",
                                text_color=COLOR_STATUS_SUCCESS,
                            )
                        self._update_managed_status(target_backend)
                    except Exception:
                        pass

                self._safe_ui_dispatch(_success_ui)

            except Exception as exc:
                logger.error("Managed runtime download failed: %s", exc)
                def _fail_ui() -> None:
                    if getattr(self, "_is_closed", False):
                        return
                    try:
                        if hasattr(self, "_lbl_download_status"):
                            self._lbl_download_status.configure(
                                text=f"Download failed: {exc}",
                                text_color=COLOR_STATUS_ERROR,
                            )
                        self._update_managed_status(target_backend)
                    except Exception:
                        pass

                self._safe_ui_dispatch(_fail_ui)
            finally:
                self._is_downloading = False

        thread = threading.Thread(target=_worker, name="RuntimeDownloadWorker", daemon=True)
        self._download_thread = thread
        if hasattr(self.parent, "_runtime_download_thread"):
            self.parent._runtime_download_thread = thread
        else:
            setattr(self.parent, "_runtime_download_thread", thread)
        thread.start()

    def _populate_fields(self, s: Settings) -> None:
        """Fill form controls with values from the given Settings object."""
        self._seg_backend.set(s.backend)
        self._ent_endpoint.delete(0, "end")
        self._ent_endpoint.insert(0, s.local_endpoint)

        if s.allow_remote:
            self._sw_allow_remote.select()
        else:
            self._sw_allow_remote.deselect()

        self._ent_timeout.delete(0, "end")
        self._ent_timeout.insert(0, str(s.timeout))

        self._ent_retries.delete(0, "end")
        self._ent_retries.insert(0, str(s.max_retries))

        # Quality
        self._slider_dpi.set(s.dpi)
        self._lbl_dpi_val.configure(text=f"{int(s.dpi)} DPI")

        self._ent_max_pages.delete(0, "end")
        if s.max_pages is not None:
            self._ent_max_pages.insert(0, str(s.max_pages))

        # Runtime Source & Managed Target Backend
        if s.runtime_mode == "custom":
            self._seg_runtime_mode.set("Custom Path")
            self._on_runtime_mode_changed("Custom Path")
        else:
            self._seg_runtime_mode.set("Managed (Auto)")
            self._on_runtime_mode_changed("Managed (Auto)")

        self._seg_managed_backend.set(s.managed_backend_override)
        self._update_managed_status(s.managed_backend_override)

        if self._is_downloading:
            self._btn_download.configure(text="Downloading...", state="disabled")
            self._lbl_download_status.configure(text="Download in progress...", text_color=COLOR_TEXT_MUTED)

        # Server
        self._ent_server_path.delete(0, "end")
        if s.llama_server_path:
            self._ent_server_path.insert(0, str(s.llama_server_path))

        self._ent_model_repo.delete(0, "end")
        self._ent_model_repo.insert(0, s.model_repo)

        if s.auto_start_server:
            self._sw_auto_start.select()
        else:
            self._sw_auto_start.deselect()

    def _on_slider_dpi_changed(self, value: float) -> None:
        """Update live DPI readout label when slider thumb moves."""
        self._lbl_dpi_val.configure(text=f"{int(value)} DPI")

    def _on_browse_server_path(self) -> None:
        """Open native file dialog to choose llama-server.exe."""
        path = filedialog.askopenfilename(
            parent=self,
            title="Locate llama-server executable",
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")],
        )
        if path:
            self._ent_server_path.delete(0, "end")
            self._ent_server_path.insert(0, str(Path(path).resolve()))

    def _on_toggle_allow_remote(self) -> None:
        """Intercept allow_remote toggle and require explicit security acknowledgment."""
        if self._sw_allow_remote.get() == 1:
            # User turned it ON -> Require explicit confirmation
            confirmed = SecurityConfirmationDialog.ask_confirmation(self)
            if not confirmed:
                self._sw_allow_remote.deselect()

    # ==========================================================================
    # Validation & Persistence
    # ==========================================================================

    def _on_cancel(self) -> None:
        """Discard changes and close dialog."""
        self.destroy()

    def _on_save(self) -> None:
        """Validate input values through Settings.__post_init__ and persist."""
        self._lbl_error_banner.pack_forget()
        try:
            if not self._lbl_restart_banner.winfo_ismapped():
                self._banner_frame.pack_forget()
        except Exception:
            pass

        backend = self._seg_backend.get().strip()
        endpoint = self._ent_endpoint.get().strip()
        allow_remote = (self._sw_allow_remote.get() == 1)
        raw_timeout = self._ent_timeout.get().strip()
        raw_retries = self._ent_retries.get().strip()
        dpi = int(self._slider_dpi.get())
        raw_max_pages = self._ent_max_pages.get().strip()
        max_pages = int(raw_max_pages) if raw_max_pages else None
        runtime_mode = "custom" if self._seg_runtime_mode.get() == "Custom Path" else "managed"
        backend_override = self._seg_managed_backend.get().strip().lower()
        server_path = self._ent_server_path.get().strip() or None
        model_repo = self._ent_model_repo.get().strip()
        auto_start = (self._sw_auto_start.get() == 1)

        # STRICT VALIDATION ORDERING:
        # Construct candidate Settings instance first.
        # If any value violates constraints (including loopback security),
        # __post_init__ raises ValueError immediately.
        try:
            new_settings = Settings(
                backend=backend,
                local_endpoint=endpoint,
                allow_remote=allow_remote,
                timeout=raw_timeout,  # type: ignore[arg-type]
                max_retries=raw_retries,  # type: ignore[arg-type]
                dpi=dpi,
                max_pages=max_pages,
                runtime_mode=runtime_mode,
                managed_backend_override=backend_override,
                llama_server_path=server_path,
                model_repo=model_repo,
                auto_start_server=auto_start,
            )
        except ValueError as val_err:
            self._banner_frame.pack(fill="x", padx=16, pady=(8, 0), before=self._action_bar)
            self._lbl_error_banner.configure(text=f"Validation Error: {val_err}")
            self._lbl_error_banner.pack(fill="x", pady=(4, 0))
            return

        # Construction succeeded; persist to .env and synchronize os.environ
        try:
            new_settings.save_to_env()
        except Exception as save_err:
            self._banner_frame.pack(fill="x", padx=16, pady=(8, 0), before=self._action_bar)
            self._lbl_error_banner.configure(text=f"Failed to save .env: {save_err}")
            self._lbl_error_banner.pack(fill="x", pady=(4, 0))
            return

        # Check if managed server is actively running and requires a restart
        new_server_config = (
            str(new_settings.effective_llama_server_path or ""),
            str(new_settings.model_repo),
            str(new_settings.local_endpoint),
        )
        server_config_changed = (new_server_config != self._initial_server_config)

        if self.server_manager and getattr(self.server_manager, "is_managed", False):
            if server_config_changed:
                logger.info("Managed server settings changed; restart required")
                # Show restart required banner on parent / callback
                if hasattr(self.parent, "show_restart_required_banner"):
                    self.parent.show_restart_required_banner()

        # Invoke callback to update runtime app and engine settings
        if self.on_save_callback:
            try:
                self.on_save_callback(new_settings)
            except Exception as cb_err:
                logger.warning("Error invoking settings on_save_callback: %s", cb_err)

        self.destroy()

    def destroy(self) -> None:
        """Mark modal window as closed and release GUI resources."""
        self._is_closed = True
        super().destroy()
