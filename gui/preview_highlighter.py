"""Markdown preview typography tagger for AksaraSight Desktop Studio.

Parses markdown text buffers and applies rich styling tags to Tk text widgets.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from gui.theme import (
    COLOR_ACCENT_TEXT,
    COLOR_SURFACE_1,
    COLOR_SURFACE_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)


class MarkdownHighlighter:
    """Configures and applies rich typography tags for markdown preview."""

    TAGS = (
        "h1",
        "h2",
        "h3",
        "bold",
        "italic",
        "code_inline",
        "code_block",
        "table_header",
        "table_row",
        "bullet",
        "divider",
        "muted",
    )

    def configure_tags(self, textbox: Any) -> None:
        """Configure rich markdown tags on the underlying Tk text widget."""
        tw = getattr(textbox, "_textbox", textbox)
        tw.tag_config("h1", font=("Segoe UI", 15, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("h2", font=("Segoe UI", 13, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("h3", font=("Segoe UI", 12, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("bold", font=("Segoe UI", 12, "bold"), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("italic", font=("Segoe UI", 12, "italic"), foreground=COLOR_TEXT_SECONDARY)
        tw.tag_config("code_inline", font=("Consolas", 11), foreground=COLOR_ACCENT_TEXT, background=COLOR_SURFACE_1)
        tw.tag_config("code_block", font=("Consolas", 11), foreground=COLOR_TEXT_PRIMARY, background=COLOR_SURFACE_1)
        tw.tag_config(
            "table_header", font=("Consolas", 11, "bold"), foreground=COLOR_ACCENT_TEXT, background=COLOR_SURFACE_1
        )
        tw.tag_config("table_row", font=("Consolas", 11), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("bullet", font=("Segoe UI", 12), foreground=COLOR_TEXT_PRIMARY)
        tw.tag_config("divider", foreground=COLOR_SURFACE_BORDER)
        tw.tag_config("muted", foreground=COLOR_TEXT_MUTED)

    def clear_tags(self, textbox: Any) -> None:
        """Remove all formatting tags from the preview text widget."""
        tw = getattr(textbox, "_textbox", textbox)
        for tag in self.TAGS:
            tw.tag_remove(tag, "1.0", "end")

    def apply_tags(
        self,
        textbox: Any,
        markdown_text: Optional[str] = None,
        color_tokens: Optional[dict[str, Any]] = None,
    ) -> None:
        """Parse text in the preview widget and apply typography tags."""
        tw = getattr(textbox, "_textbox", textbox)
        self.clear_tags(tw)

        end_index = tw.index("end-1c")
        if not end_index or "." not in end_index:
            return
        total_lines = int(end_index.split(".")[0])
        in_code_block = False

        for line_no in range(1, total_lines + 1):
            start_idx = f"{line_no}.0"
            end_idx = f"{line_no}.end"
            line = tw.get(start_idx, end_idx)
            stripped = line.strip()

            # Fenced code block check
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                tw.tag_add("muted", start_idx, end_idx)
                continue

            if in_code_block:
                tw.tag_add("code_block", start_idx, end_idx)
                continue

            if not stripped:
                continue

            # Headings
            if stripped.startswith("# "):
                tw.tag_add("h1", start_idx, end_idx)
                continue
            elif stripped.startswith("## "):
                tw.tag_add("h2", start_idx, end_idx)
                continue
            elif stripped.startswith("### "):
                tw.tag_add("h3", start_idx, end_idx)
                continue

            # Horizontal dividers
            if stripped in ("---", "***", "___") or re.match(r"^[-*_]{3,}$", stripped):
                tw.tag_add("divider", start_idx, end_idx)
                continue

            # Table rows
            if stripped.startswith("|") and stripped.endswith("|"):
                if re.match(r"^\|[\s\-:|]+\|$", stripped):
                    tw.tag_add("muted", start_idx, end_idx)
                else:
                    prev_line = tw.get(f"{line_no-1}.0", f"{line_no-1}.end").strip() if line_no > 1 else ""
                    if not (prev_line.startswith("|") and prev_line.endswith("|")):
                        tw.tag_add("table_header", start_idx, end_idx)
                    else:
                        tw.tag_add("table_row", start_idx, end_idx)
                continue

            # Unordered & ordered list bullets
            if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped):
                tw.tag_add("bullet", start_idx, end_idx)

            # Blockquotes
            if stripped.startswith(">"):
                tw.tag_add("italic", start_idx, end_idx)
                continue

            # Inline code: `code`
            for m in re.finditer(r"`([^`]+)`", line):
                tw.tag_add("code_inline", f"{line_no}.{m.start()}", f"{line_no}.{m.end()}")

            # Bold: **bold** or __bold__
            for m in re.finditer(r"(\*\*|__)(.*?)\1", line):
                tw.tag_add("bold", f"{line_no}.{m.start()}", f"{line_no}.{m.end()}")

            # Italic: *text*
            for m in re.finditer(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", line):
                tw.tag_add("italic", f"{line_no}.{m.start()}", f"{line_no}.{m.end()}")
