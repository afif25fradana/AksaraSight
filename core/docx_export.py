"""DOCX document generation and serialization from OCR markdown AST."""

from html.parser import HTMLParser
import io
import logging
from typing import Any, List, Optional, Sequence, Tuple

import docx
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from core.models import JobStatus, OCRResult

logger = logging.getLogger(__name__)


def _create_markdown_parser() -> MarkdownIt:
    """Instantiate a MarkdownIt parser with GFM pipe tables and strikethrough enabled."""
    return MarkdownIt().enable("table").enable("strikethrough")


def _render_inline_nodes(
    paragraph: Paragraph,
    nodes: Sequence[SyntaxTreeNode],
    bold: bool = False,
    italic: bool = False,
    strike: bool = False,
    font_name: Optional[str] = None,
    font_size: Optional[Pt] = None,
) -> None:
    """Recursively render inline Markdown AST nodes as runs within a parent paragraph.

    Handles bold (**), italic (*), strikethrough (~~), inline code (`code`),
    soft breaks, hard breaks, and raw text (including LaTeX math syntax).
    """
    for node in nodes:
        if node.type == "text":
            run = paragraph.add_run(node.content)
            run.bold = bold
            run.italic = italic
            run.font.strike = strike
            if font_name:
                run.font.name = font_name
            if font_size:
                run.font.size = font_size
        elif node.type == "strong":
            _render_inline_nodes(
                paragraph,
                node.children,
                bold=True,
                italic=italic,
                strike=strike,
                font_name=font_name,
                font_size=font_size,
            )
        elif node.type == "em":
            _render_inline_nodes(
                paragraph,
                node.children,
                bold=bold,
                italic=True,
                strike=strike,
                font_name=font_name,
                font_size=font_size,
            )
        elif node.type == "s":
            _render_inline_nodes(
                paragraph,
                node.children,
                bold=bold,
                italic=italic,
                strike=True,
                font_name=font_name,
                font_size=font_size,
            )
        elif node.type == "code_inline":
            # Inline code: styled run inside the CURRENT paragraph, never an indented block
            run = paragraph.add_run(node.content)
            run.font.name = "Consolas"
            run.font.size = font_size or Pt(10)
            run.bold = bold
            run.italic = italic
        elif node.type == "softbreak":
            paragraph.add_run(" ")
        elif node.type == "hardbreak":
            paragraph.add_run("\n")
        elif node.type == "image":
            # Images cannot be embedded; emit a visible placeholder using alt text
            alt = node.content or (node.children[0].content if node.children else "")
            run = paragraph.add_run(f"[image: {alt}]")
            run.bold = bold
            run.italic = italic
        else:
            # Fallback for nested elements or raw content
            if node.children:
                _render_inline_nodes(
                    paragraph,
                    node.children,
                    bold=bold,
                    italic=italic,
                    strike=strike,
                    font_name=font_name,
                    font_size=font_size,
                )
            elif node.content:
                run = paragraph.add_run(node.content)
                run.bold = bold
                run.italic = italic
                run.font.strike = strike


def _extract_alignment(style_str: str) -> WD_ALIGN_PARAGRAPH:
    """Resolve paragraph alignment from CSS style attribute string."""
    if "text-align:center" in style_str or "text-align: center" in style_str:
        return WD_ALIGN_PARAGRAPH.CENTER
    if "text-align:right" in style_str or "text-align: right" in style_str:
        return WD_ALIGN_PARAGRAPH.RIGHT
    return WD_ALIGN_PARAGRAPH.LEFT


MAX_WORD_TABLE_COLUMNS = 63
"""Maximum table column count supported by Microsoft Word.

Microsoft Word enforces an application-level limit of 63 columns per table, as commonly documented in Word operating parameter specifications.
Empirically observed via COM automation with Microsoft Word 2016 (Office 16 64-bit on Windows 11, one 2-row test file): an OOXML table with 64 columns opened without a crash, but Word silently collapsed it to 63 columns, merging the 64th cell's content into the 63rd column with no user warning.
"""

MAX_HTML_TABLE_ROWS = 1000
"""Maximum table row count rendered before truncation to avoid memory and performance degradation."""


def _append_table_truncation_note(
    doc: docx.document.Document,
    truncated_rows: int = 0,
    truncated_cols: int = 0,
) -> None:
    """Append a visible italic notice or spacer paragraph after a table.

    Formats:
    - Both: "[Table truncated: {truncated_rows} rows and {truncated_cols} columns omitted to fit document limits]"
    - Rows only: "[Table truncated: {truncated_rows} rows omitted to fit document limits]"
    - Columns only: "[Table truncated: {truncated_cols} columns omitted to fit document limits]"

    Style: Italic, Pt(8.5), paragraph space_before=0, space_after=6.
    """
    if truncated_rows <= 0 and truncated_cols <= 0:
        p_after = doc.add_paragraph()
        p_after.paragraph_format.space_before = Pt(0)
        p_after.paragraph_format.space_after = Pt(6)
        return

    if truncated_rows > 0 and truncated_cols > 0:
        msg = f"[Table truncated: {truncated_rows} rows and {truncated_cols} columns omitted to fit document limits]"
    elif truncated_rows > 0:
        msg = f"[Table truncated: {truncated_rows} rows omitted to fit document limits]"
    else:
        msg = f"[Table truncated: {truncated_cols} columns omitted to fit document limits]"

    logger.warning(
        "Table truncated: %d rows, %d columns omitted to fit document limits",
        truncated_rows,
        truncated_cols,
    )
    p_note = doc.add_paragraph()
    p_note.paragraph_format.space_before = Pt(0)
    p_note.paragraph_format.space_after = Pt(6)
    run = p_note.add_run(msg)
    run.italic = True
    run.font.size = Pt(8.5)


def _render_table_node(doc: docx.document.Document, table_node: SyntaxTreeNode) -> None:
    """Render a GFM pipe table node with ragged row padding and OOXML attributes.

    Ensures:
    - Uniform rectangular column count across all rows (ragged rows padded with empty cells).
    - Table Grid style with bold header row.
    - Raw OOXML w:tblHeader and w:cantSplit attributes on header row.
    - Raw OOXML w:cantSplit attributes on all data rows.
    - Clamped to MAX_WORD_TABLE_COLUMNS (63) and MAX_HTML_TABLE_ROWS (1000) with visible truncation note.
    - Verbatim preservation of numeric formatting (decimals, commas, negative values).
    """
    rows_data: List[List[dict]] = []

    for section in table_node.children:  # thead, tbody
        for tr in section.children:
            row_cells = []
            for cell in tr.children:
                is_header = cell.type == "th"
                align = _extract_alignment(str(cell.attrs.get("style", "")))
                # The first child of a th/td node is typically an 'inline' node
                inline_node = cell.children[0] if cell.children else None
                row_cells.append({
                    "is_header": is_header,
                    "align": align,
                    "inline_node": inline_node,
                })
            rows_data.append(row_cells)

    if not rows_data:
        return

    truncated_rows = 0
    if len(rows_data) > MAX_HTML_TABLE_ROWS:
        truncated_rows = len(rows_data) - MAX_HTML_TABLE_ROWS
        rows_data = rows_data[:MAX_HTML_TABLE_ROWS]

    # Calculate max columns across all rows to pad ragged rows
    max_cols = max(len(r) for r in rows_data)
    if max_cols == 0:
        return

    truncated_cols = 0
    if max_cols > MAX_WORD_TABLE_COLUMNS:
        truncated_cols = max_cols - MAX_WORD_TABLE_COLUMNS
        cols_to_render = MAX_WORD_TABLE_COLUMNS
    else:
        cols_to_render = max_cols

    # Normalize ragged rows by clamping or padding to cols_to_render
    for r in rows_data:
        if len(r) > cols_to_render:
            r[:] = r[:cols_to_render]
        while len(r) < cols_to_render:
            r.append({
                "is_header": False,
                "align": WD_ALIGN_PARAGRAPH.LEFT,
                "inline_node": None,
            })

    table = doc.add_table(rows=len(rows_data), cols=cols_to_render)
    table.style = "Table Grid"

    for row_idx, row_cells in enumerate(rows_data):
        row = table.rows[row_idx]
        trPr = row._tr.get_or_add_trPr()

        # Split-prevention on all rows
        trPr.append(OxmlElement("w:cantSplit"))

        is_header_row = row_cells[0]["is_header"] if row_cells else False
        if is_header_row:
            # Repeat header on new pages across Word pagination
            trPr.append(OxmlElement("w:tblHeader"))

        for col_idx, cell_data in enumerate(row_cells):
            cell = row.cells[col_idx]
            p = cell.paragraphs[0]
            p.alignment = cell_data["align"]
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)

            inline = cell_data["inline_node"]
            if inline and inline.children:
                _render_inline_nodes(
                    p,
                    inline.children,
                    bold=is_header_row,
                )
            elif inline and inline.content:
                run = p.add_run(inline.content)
                run.bold = is_header_row

    _append_table_truncation_note(
        doc,
        truncated_rows=truncated_rows,
        truncated_cols=truncated_cols,
    )


class _HTMLTableExtractor(HTMLParser):
    """HTML parser extracting table grids and non-table text with charref decoding.

    Clamped to 63 columns to adhere to Microsoft Word's application table column limit
    (documented in Microsoft Word operating parameter limitations).
    """

    def __init__(self, max_rows: int = MAX_HTML_TABLE_ROWS) -> None:
        super().__init__(convert_charrefs=True)
        self.max_rows = max_rows
        self.tables: List[List[List[dict]]] = []
        self.non_table_text: List[str] = []
        self.sequence: List[Tuple[Any, ...]] = []
        self._current_table: List[List[dict]] = []
        self._current_row: List[dict] = []
        self._cell_text: List[str] = []
        self._current_truncated_rows = 0
        self._in_table = False
        self._table_depth = 0
        self._nested_table_rows = 0
        self._in_tr = False
        self._in_cell = False
        self._cell_is_header = False
        self._cell_colspan = 1
        self._cell_rowspan = 1
        self._cell_align = WD_ALIGN_PARAGRAPH.LEFT

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attrs_dict = {k.lower(): v for k, v in attrs if v is not None}

        if tag == "table":
            self._table_depth += 1
            if self._table_depth > 1:
                self._nested_table_rows = 0
                return
            if self._in_cell:
                self._flush_cell()
            if self._in_tr:
                self._flush_row()
            if self._in_table:
                self._flush_table()
            self._in_table = True
            self._current_table = []
            self._in_tr = False
            self._in_cell = False
            return

        if self._table_depth > 1:
            if tag == "tr":
                if self._nested_table_rows > 0 and self._cell_text and not self._cell_text[-1].endswith("\n"):
                    self._cell_text.append("\n")
                self._nested_table_rows += 1
                return
            if tag in ("td", "th"):
                if self._cell_text and not self._cell_text[-1].endswith((" ", "\n")):
                    self._cell_text.append(" ")
                return

        if tag == "tr":
            if self._in_cell:
                self._flush_cell()
            if self._in_tr:
                self._flush_row()
            if len(self._current_table) >= self.max_rows:
                self._current_truncated_rows += 1
                return
            self._in_tr = True
            self._current_row = []
        elif tag in ("th", "td"):
            if len(self._current_table) >= self.max_rows:
                return
            if self._in_cell:
                self._flush_cell()
            if not self._in_tr:
                self._in_tr = True
                self._current_row = []
            self._in_cell = True
            self._cell_is_header = (tag == "th")
            try:
                self._cell_colspan = min(max(1, int(attrs_dict.get("colspan", "1"))), 1000)
            except (ValueError, TypeError):
                self._cell_colspan = 1
            try:
                self._cell_rowspan = min(max(1, int(attrs_dict.get("rowspan", "1"))), self.max_rows)
            except (ValueError, TypeError):
                self._cell_rowspan = 1
            align_attr = (attrs_dict.get("align") or "").lower()
            style_attr = (attrs_dict.get("style") or "").lower()
            if align_attr == "center" or "text-align:center" in style_attr or "text-align: center" in style_attr:
                self._cell_align = WD_ALIGN_PARAGRAPH.CENTER
            elif align_attr == "right" or "text-align:right" in style_attr or "text-align: right" in style_attr:
                self._cell_align = WD_ALIGN_PARAGRAPH.RIGHT
            elif align_attr == "justify" or "text-align:justify" in style_attr:
                self._cell_align = WD_ALIGN_PARAGRAPH.JUSTIFY
            else:
                self._cell_align = WD_ALIGN_PARAGRAPH.LEFT
            self._cell_text = []
        elif tag == "p":
            if self._in_cell and self._cell_text:
                self._cell_text.append("\n")
        elif tag == "br":
            if self._in_cell:
                self._cell_text.append("\n")
            elif not self._in_table:
                self._append_non_table_text("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_depth = max(0, self._table_depth - 1)
            if self._table_depth > 0:
                self._nested_table_rows = 0
                return
            if self._in_cell:
                self._flush_cell()
            if self._in_tr:
                self._flush_row()
            if self._in_table:
                self._flush_table()
            return

        if self._table_depth > 1:
            if tag in ("th", "td", "tr"):
                return

        if tag in ("th", "td"):
            if self._in_cell:
                self._flush_cell()
        elif tag == "tr":
            if self._in_cell:
                self._flush_cell()
            if self._in_tr:
                self._flush_row()

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text.append(data)
        elif not self._in_table:
            self._append_non_table_text(data)

    def _append_non_table_text(self, data: str) -> None:
        self.non_table_text.append(data)
        if self.sequence and self.sequence[-1][0] == "text":
            self.sequence[-1] = ("text", self.sequence[-1][1] + data)
        else:
            self.sequence.append(("text", data))

    def _flush_cell(self) -> None:
        if not self._in_cell:
            return
        text = "".join(self._cell_text).strip()
        cell_dict = {
            "is_header": self._cell_is_header,
            "colspan": self._cell_colspan,
            "rowspan": self._cell_rowspan,
            "align": self._cell_align,
            "text": text,
        }
        self._current_row.append(cell_dict)
        self._cell_text = []
        self._in_cell = False
        self._nested_table_rows = 0

    def _flush_row(self) -> None:
        if self._current_row:
            if len(self._current_table) < self.max_rows:
                self._current_table.append(self._current_row)
            self._current_row = []
        self._in_tr = False

    def _flush_table(self) -> None:
        if self._current_table:
            self.tables.append(self._current_table)
            self.sequence.append(("table", self._current_table, self._current_truncated_rows))
            self._current_table = []
        self._current_truncated_rows = 0
        self._in_table = False
        self._table_depth = 0
        self._nested_table_rows = 0

    def close(self) -> None:
        super().close()
        if self._in_cell:
            self._flush_cell()
        if self._in_tr:
            self._flush_row()
        if self._in_table:
            self._flush_table()
        self._table_depth = 0
        self._nested_table_rows = 0


def _render_parsed_html_table(
    doc: docx.document.Document,
    table_data: List[List[dict]],
    truncated_rows: int = 0,
) -> None:
    """Render a parsed HTML table into the Document with merge and OOXML attributes.

    Clamped to 63 columns to adhere to Microsoft Word's application table column limit
    (documented in Microsoft Learn / [MS-OODF3] Section 9.1.6).
    """
    if not table_data:
        return

    occupied: set[Tuple[int, int]] = set()
    placements: List[Tuple[int, int, dict, int, int]] = []
    max_attempted_cols = 0

    for r, row in enumerate(table_data):
        col = 0
        for cell_dict in row:
            while (r, col) in occupied:
                col += 1
            raw_colspan = max(1, int(cell_dict.get("colspan", 1)))
            raw_rowspan = max(1, int(cell_dict.get("rowspan", 1)))
            attempted_end_col = col + raw_colspan
            if attempted_end_col > max_attempted_cols:
                max_attempted_cols = attempted_end_col

            for dr in range(raw_rowspan):
                for dc in range(raw_colspan):
                    occupied.add((r + dr, col + dc))

            if col < MAX_WORD_TABLE_COLUMNS:
                colspan = min(raw_colspan, MAX_WORD_TABLE_COLUMNS - col)
                rowspan = min(raw_rowspan, max(1, len(table_data) - r))
                placements.append((r, col, cell_dict, rowspan, colspan))
            else:
                logger.warning(
                    "HTML table row %d column %d exceeded column limit %d; cell omitted",
                    r,
                    col,
                    MAX_WORD_TABLE_COLUMNS,
                )

            col += raw_colspan

    if not placements:
        return

    total_rows = max(r + rowspan for r, col, cell, rowspan, colspan in placements)
    max_cols = max(col + colspan for r, col, cell, rowspan, colspan in placements)

    if total_rows == 0 or max_cols == 0:
        return

    table = doc.add_table(rows=total_rows, cols=max_cols)
    table.style = "Table Grid"

    for r, col, cell_dict, rowspan, colspan in placements:
        if rowspan > 1 or colspan > 1:
            target_cell = table.cell(r, col).merge(
                table.cell(r + rowspan - 1, col + colspan - 1)
            )
        else:
            target_cell = table.cell(r, col)

        p = target_cell.paragraphs[0] if target_cell.paragraphs else target_cell.add_paragraph()
        p.alignment = cell_dict.get("align", WD_ALIGN_PARAGRAPH.LEFT)
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)

        text = cell_dict.get("text", "")
        if text:
            run = p.add_run(text)
            if cell_dict.get("is_header"):
                run.bold = True
            run.font.size = Pt(9.5)

    for row_idx, row in enumerate(table.rows):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        if row_idx < len(table_data) and any(c.get("is_header") for c in table_data[row_idx]):
            trPr.append(OxmlElement("w:tblHeader"))

    truncated_cols = max(0, max_attempted_cols - MAX_WORD_TABLE_COLUMNS)
    _append_table_truncation_note(
        doc,
        truncated_rows=truncated_rows,
        truncated_cols=truncated_cols,
    )

def _render_ast_node(doc: docx.document.Document, node: SyntaxTreeNode, depth: int = 0) -> None:
    """Render an individual top-level block node into the Document."""
    if node.type == "heading":
        level = 1
        if node.tag == "h2":
            level = 2
        elif node.tag in ("h3", "h4", "h5", "h6"):
            level = 3
        p = doc.add_paragraph(style=f"Heading {level}")
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        if node.children and node.children[0].type == "inline":
            _render_inline_nodes(p, node.children[0].children)

    elif node.type == "paragraph":
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(6)
        if node.children and node.children[0].type == "inline":
            _render_inline_nodes(p, node.children[0].children)

    elif node.type in ("fence", "code_block"):
        # Fenced/indented code block: standalone indented monospace paragraph
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(36)
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(node.content.rstrip("\n"))
        run.font.name = "Consolas"
        run.font.size = Pt(9.5)

    elif node.type == "blockquote":
        # Blockquote: standalone indented monospace paragraph without shaded callouts
        for child in node.children:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(36)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(4)
            if child.children and child.children[0].type == "inline":
                _render_inline_nodes(
                    p,
                    child.children[0].children,
                    font_name="Consolas",
                    font_size=Pt(9.5),
                )
            elif child.content:
                run = p.add_run(child.content)
                run.font.name = "Consolas"
                run.font.size = Pt(9.5)

    elif node.type == "bullet_list":
        for item in node.children:
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Pt(18 * (depth + 1))
            for sub_child in item.children:
                if sub_child.type in ("bullet_list", "ordered_list"):
                    _render_ast_node(doc, sub_child, depth=depth + 1)
                elif sub_child.children and sub_child.children[0].type == "inline":
                    _render_inline_nodes(p, sub_child.children[0].children)
                elif sub_child.content:
                    p.add_run(sub_child.content)

    elif node.type == "ordered_list":
        for item in node.children:
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.left_indent = Pt(18 * (depth + 1))
            for sub_child in item.children:
                if sub_child.type in ("bullet_list", "ordered_list"):
                    _render_ast_node(doc, sub_child, depth=depth + 1)
                elif sub_child.children and sub_child.children[0].type == "inline":
                    _render_inline_nodes(p, sub_child.children[0].children)
                elif sub_child.content:
                    p.add_run(sub_child.content)

    elif node.type == "table":
        _render_table_node(doc, node)

    elif node.type == "hr":
        # Visual separator divider paragraph, NEVER a page break
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("―" * 32)
        run.font.color.rgb = RGBColor(160, 160, 160)

    else:
        # Fallback for unrecognized block nodes
        if node.children:
            for child in node.children:
                _render_ast_node(doc, child, depth=depth)
        elif node.content:
            p = doc.add_paragraph()
            p.add_run(node.content)


_TABLE_TAG_FRAGMENTS = (
    "<tr",
    "<td",
    "<th",
    "</table",
    "<tbody",
    "</tbody",
    "<thead",
    "</thead",
    "<tfoot",
    "</tfoot",
)


def render_markdown_page(
    doc: docx.document.Document,
    markdown_text: str,
    parser: Optional[MarkdownIt] = None,
    max_html_table_rows: int = MAX_HTML_TABLE_ROWS,
) -> None:
    """Parse and render a single page's markdown string into the target Document."""
    if not markdown_text.strip():
        return
    md_parser = parser or _create_markdown_parser()
    tokens = md_parser.parse(markdown_text)
    root = SyntaxTreeNode(tokens)
    children = root.children
    idx = 0
    while idx < len(children):
        node = children[idx]
        if node.type == "html_block" and "<table" in node.content.lower():
            accumulated_html = [node.content]
            while (
                idx + 1 < len(children)
                and "</table>" not in "".join(accumulated_html).lower()
            ):
                next_node = children[idx + 1]
                if (
                    next_node.type == "html_block"
                    and any(frag in next_node.content.lower() for frag in _TABLE_TAG_FRAGMENTS)
                    and not next_node.content.lower().lstrip().startswith("<table")
                ):
                    idx += 1
                    accumulated_html.append(children[idx].content)
                else:
                    break

            html_str = "\n".join(accumulated_html)
            extractor = _HTMLTableExtractor(max_rows=max_html_table_rows)
            extractor.feed(html_str)
            extractor.close()

            for item in extractor.sequence:
                if item[0] == "table":
                    _render_parsed_html_table(doc, item[1], truncated_rows=item[2])
                elif item[0] == "text":
                    for line in item[1].splitlines():
                        stripped = line.strip()
                        if stripped:
                            p = doc.add_paragraph()
                            p.paragraph_format.space_before = Pt(0)
                            p.paragraph_format.space_after = Pt(6)
                            p.add_run(stripped)
            idx += 1
        else:
            _render_ast_node(doc, node)
            idx += 1


def build_docx(result: OCRResult) -> docx.document.Document:
    """Build a styled Microsoft Word Document from an aggregated OCRResult.

    Functional guarantees:
    1. Page breaks: doc.add_page_break() inserted strictly between consecutive
       valid pages from result.pages (never after the last page). Internal '---'
       horizontal rules are rendered as visual divider paragraphs.
    2. Tables: ragged rows padded to max_cols, escaped pipes handled, empty cells
       supported, numeric formatting preserved, 'Table Grid' style applied, and
       OOXML w:tblHeader and w:cantSplit attributes added to rows.
    3. Headings: mapped to Word Heading 1, 2, and 3 styles.
    4. Code & Blockquotes: rendered as plain indented paragraphs in Consolas.
       Inline code spans remain inline runs without creating paragraphs or indentation.
    5. LaTeX math: rendered inline as plain/monospace text exactly as written.

    Args:
        result: Aggregated document OCRResult instance.

    Returns:
        docx.document.Document: The generated python-docx Document instance.
    """
    doc = Document()
    valid_pages = [
        p for p in result.pages
        if p.status in (JobStatus.SUCCESS, JobStatus.PARTIAL) and p.markdown.strip()
    ]

    if not valid_pages:
        # Fallback for empty or all-failed results: return clean minimal document
        if result.error:
            p = doc.add_paragraph(f"Error: {result.error}")
            p.paragraph_format.space_before = Pt(12)
        return doc

    parser = _create_markdown_parser()
    total_pages = len(valid_pages)

    for page_idx, page in enumerate(valid_pages):
        render_markdown_page(doc, page.markdown, parser=parser)
        # Add page break strictly between pages, never after the final page
        if page_idx < total_pages - 1:
            doc.add_page_break()

    return doc



def export_to_docx_bytes(result: OCRResult) -> bytes:
    """Serialize an OCRResult to DOCX binary bytes in memory.

    Args:
        result: Aggregated OCRResult instance.

    Returns:
        bytes: Binary OpenXML DOCX archive payload.
    """
    buf = io.BytesIO()
    doc = build_docx(result)
    doc.save(buf)
    return buf.getvalue()
