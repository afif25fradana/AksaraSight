"""DOCX document generation and serialization from OCR markdown AST."""

import io
from pathlib import Path
from typing import BinaryIO, List, Optional, Sequence, Union

import docx
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from core.models import JobStatus, OCRResult


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


def _render_table_node(doc: docx.Document, table_node: SyntaxTreeNode) -> None:
    """Render a GFM pipe table node with ragged row padding and OOXML attributes.

    Ensures:
    - Uniform rectangular column count across all rows (ragged rows padded with empty cells).
    - Table Grid style with bold header row.
    - Raw OOXML w:tblHeader and w:cantSplit attributes on header row.
    - Raw OOXML w:cantSplit attributes on all data rows.
    - Verbatim preservation of numeric formatting (decimals, commas, negative values).
    """
    rows_data: List[List[dict]] = []

    for section in table_node.children:  # thead, tbody
        for tr in section.children:
            row_cells = []
            for cell in tr.children:
                is_header = cell.type == "th"
                align = _extract_alignment(cell.attrs.get("style", ""))
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

    # Calculate max columns across all rows to pad ragged rows
    max_cols = max(len(r) for r in rows_data)
    if max_cols == 0:
        return

    # Normalize ragged rows by padding with empty cells
    for r in rows_data:
        while len(r) < max_cols:
            r.append({
                "is_header": False,
                "align": WD_ALIGN_PARAGRAPH.LEFT,
                "inline_node": None,
            })

    table = doc.add_table(rows=len(rows_data), cols=max_cols)
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

    # Add spacing after table
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(6)


def _render_ast_node(doc: docx.Document, node: SyntaxTreeNode) -> None:
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
            for sub_child in item.children:
                if sub_child.children and sub_child.children[0].type == "inline":
                    _render_inline_nodes(p, sub_child.children[0].children)
                elif sub_child.content:
                    p.add_run(sub_child.content)

    elif node.type == "ordered_list":
        for item in node.children:
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2)
            for sub_child in item.children:
                if sub_child.children and sub_child.children[0].type == "inline":
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
                _render_ast_node(doc, child)
        elif node.content:
            p = doc.add_paragraph()
            p.add_run(node.content)


def render_markdown_page(doc: docx.Document, markdown_text: str, parser: Optional[MarkdownIt] = None) -> None:
    """Parse and render a single page's markdown string into the target Document."""
    if not markdown_text.strip():
        return
    md_parser = parser or _create_markdown_parser()
    tokens = md_parser.parse(markdown_text)
    root = SyntaxTreeNode(tokens)
    for block_node in root.children:
        _render_ast_node(doc, block_node)


def build_docx(result: OCRResult) -> docx.Document:
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
        docx.Document: The generated python-docx Document instance.
    """
    doc = Document()
    valid_pages = [
        p for p in result.pages
        if p.status == JobStatus.SUCCESS and p.markdown.strip()
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


def export_to_docx(result: OCRResult, target: Union[str, Path, BinaryIO]) -> Path:
    """Export an OCRResult to a .docx Word document file or stream.

    Args:
        result: Aggregated OCRResult instance.
        target: Target destination file path or writable binary stream.

    Returns:
        Path: Target path if target was a path, or Path('exported.docx') if stream.
    """
    doc = build_docx(result)
    doc.save(target)
    if isinstance(target, (str, Path)):
        return Path(target).resolve()
    return Path("exported.docx")


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
