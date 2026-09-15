"""Calm Trust design system color tokens for AksaraSight Local Desktop Studio.

WCAG 2.1 AA / AAA compliant palette. Provides base surfaces, borders,
text colors, accent colors, status dot indicators, and file-type chips.
Decoupled into a dedicated constants module to prevent circular imports
between GUI windows and main application shell.
"""

# Base Surface & Canvas Tokens
COLOR_CANVAS_BG = "#121417"
COLOR_SURFACE_1 = "#1a1d21"
COLOR_SURFACE_2 = "#22262b"
COLOR_SURFACE_BORDER = "#2e333b"
COLOR_SURFACE_BORDER_HOVER = "#3d444e"
COLOR_INTERACTIVE_NEUTRAL = "#252a31"
COLOR_INTERACTIVE_HOVER = "#2f3640"
COLOR_ROW_SELECTED_BG = "#2a3745"

# Accent Tokens (Slate Blue)
COLOR_ACCENT_PRIMARY = "#2e6e91"
COLOR_ACCENT_HOVER = "#3b82a6"
COLOR_ACCENT_DISABLED = "#1e3847"
COLOR_ACCENT_DISABLED_TEXT = "#8da5b5"
COLOR_ACCENT_TEXT = "#56a0c7"

# Scrollbar Tokens
COLOR_SCROLLBAR_THUMB = "#2a303a"
COLOR_SCROLLBAR_THUMB_HOVER = "#38414e"

# Typography Tokens (WCAG 2.1 AA/AAA compliant)
COLOR_TEXT_PRIMARY = "#f1f3f5"
COLOR_TEXT_SECONDARY = "#9ca3af"
COLOR_TEXT_MUTED = "#94a3b8"
COLOR_TEXT_SUBTLE = "#94a3b8"

# Status Dot Tokens
COLOR_STATUS_QUEUED = "#94a3b8"
COLOR_STATUS_PROCESSING = "#38bdf8"
COLOR_STATUS_SUCCESS = "#34d399"
COLOR_STATUS_PARTIAL = "#fbbf24"
COLOR_STATUS_WARNING = "#fbbf24"
COLOR_STATUS_FAILED = "#fb7185"
COLOR_STATUS_ERROR = "#fb7185"
COLOR_STATUS_CANCELLED = "#94a3b8"

# File Type Chips
COLOR_CHIP_PDF_BG = "#331e24"
COLOR_CHIP_PDF_TEXT = "#fb7185"
COLOR_CHIP_IMG_BG = "#182c3d"
COLOR_CHIP_IMG_TEXT = "#38bdf8"

# Drag & Drop Highlight
COLOR_DRAGOVER_BG = "#192833"


def align_segmented_button_corners(seg: object, parent_bg: str) -> None:
    """Align outer segment button canvas background with parent surface.

    CTkSegmentedButton buttons inherit their master's fg_color as their canvas
    background by default. On scaled displays, subpixel canvas allocation can leave
    an unpainted outer edge where this canvas background bleeds through outside the
    outer rounded corner curve. Setting the last segment button's bg_color to the
    surrounding parent container background eliminates this corner clipping notch.
    """
    values = getattr(seg, "cget", lambda k: [])("values")
    buttons_dict = getattr(seg, "_buttons_dict", {})
    if values and len(values) > 0 and buttons_dict:
        last_btn = buttons_dict.get(values[-1])
        if last_btn is not None and hasattr(last_btn, "configure"):
            last_btn.configure(bg_color=parent_bg)

