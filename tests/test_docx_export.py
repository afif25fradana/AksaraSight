"""Unit tests for DOCX export converter (core/docx_export.py)."""

import io
from pathlib import Path
import pytest
from docx import Document
from docx.shared import Pt

from core.docx_export import (
    build_docx,
    export_to_docx_bytes,
)
from core.models import JobStatus, OCRResult, PageResult


# ==============================================================================
# Requirement 1: Page Breaks
# ==============================================================================

def test_page_breaks_between_pages_only(tmp_path: Path) -> None:
    """Requirement 1: Verify literal page breaks are inserted strictly between pages and never after the last page."""
    result = OCRResult(
        file_path="multipage.pdf",
        pages=[
            PageResult(page_num=1, markdown="# Page One\nFirst page content.", status=JobStatus.SUCCESS),
            PageResult(page_num=2, markdown="# Page Two\nSecond page content.", status=JobStatus.SUCCESS),
            PageResult(page_num=3, markdown="# Page Three\nThird page content.", status=JobStatus.SUCCESS),
        ],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "multipage_breaks.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    paragraphs = reopened.paragraphs

    # Count page breaks across all runs in all paragraphs
    # In python-docx/OOXML, a page break is represented as a <w:br w:type="page"/> element within a run
    page_break_count = 0
    for p in paragraphs:
        for r in p.runs:
            if '<w:br w:type="page"/>' in r._r.xml:
                page_break_count += 1

    # Between 3 pages, there must be exactly 2 page breaks
    assert page_break_count == 2, f"Expected exactly 2 page breaks for 3 pages, found {page_break_count}"

    # Verify the last paragraph does not have a trailing page break
    last_paragraph = paragraphs[-1]
    for r in last_paragraph.runs:
        assert '<w:br w:type="page"/>' not in r._r.xml


def test_internal_horizontal_rule_is_not_page_break(tmp_path: Path) -> None:
    """Requirement 1: Verify markdown '---' inside a single page is rendered as visual divider, not a page break."""
    result = OCRResult(
        file_path="single_page_divider.pdf",
        pages=[
            PageResult(
                page_num=1,
                markdown="Top Section\n\n---\n\nBottom Section",
                status=JobStatus.SUCCESS,
            ),
        ],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "single_hr.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    paragraphs = reopened.paragraphs

    # Verify zero page breaks exist
    page_breaks = [
        r for p in paragraphs for r in p.runs
        if '<w:br w:type="page"/>' in r._r.xml
    ]
    assert len(page_breaks) == 0, "Internal horizontal rule '---' must not produce a page break"

    # Verify visual divider exists (rendered with divider characters)
    divider_found = any("―" in p.text for p in paragraphs)
    assert divider_found, "Internal horizontal rule should render as visual divider paragraph"


# ==============================================================================
# Requirement 2: GFM Tables & OOXML Round-Trip Tests
# ==============================================================================

def test_table_ooxml_header_repeat_and_cant_split(tmp_path: Path) -> None:
    """Requirement 2: Verify OOXML w:tblHeader and w:cantSplit attributes on raw XML round-trip."""
    table_md = (
        "| School Region | Total Enrolled | Pass Rate |\n"
        "|:---|:---:|---:|\n"
        "| Region 1 | 1,250 | 94.5% |\n"
        "| Region 2 | 890 | 88.2% |\n"
    )
    result = OCRResult(
        file_path="table.pdf",
        pages=[PageResult(page_num=1, markdown=table_md, status=JobStatus.SUCCESS)],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "ooxml_table.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    assert len(reopened.tables) == 1
    table = reopened.tables[0]

    # Verify style
    assert table.style is not None
    assert table.style.name == "Table Grid"

    # Row 0: Header row must have tblHeader and cantSplit in raw XML
    header_tr_xml = table.rows[0]._tr.xml
    assert "<w:tblHeader/>" in header_tr_xml or "<w:tblHeader" in header_tr_xml, (
        "Header row missing <w:tblHeader/> repeat element in OOXML"
    )
    assert "<w:cantSplit/>" in header_tr_xml or "<w:cantSplit" in header_tr_xml, (
        "Header row missing <w:cantSplit/> element in OOXML"
    )

    # Row 1: Data row must have cantSplit, but NOT tblHeader
    data_tr_xml = table.rows[1]._tr.xml
    assert "<w:cantSplit/>" in data_tr_xml or "<w:cantSplit" in data_tr_xml, (
        "Data row missing <w:cantSplit/> element in OOXML"
    )
    assert "<w:tblHeader" not in data_tr_xml, "Data row must not have tblHeader attribute"


def test_messy_table_edge_cases(tmp_path: Path) -> None:
    """Requirement 2: Verify ragged rows padding, escaped pipes, empty cells, and numeric fidelity."""
    # Table containing:
    # 1. Escaped pipe \| in header
    # 2. Uneven columns (row 1 has 3 cells, row 2 has 2 cells, row 3 has empty cells)
    # 3. Numeric values with decimals, commas, negative signs, percentages
    messy_md = (
        "| Metric \\| Name | Value | Percentage |\n"
        "|:---|---:|---:|\n"
        "| Total Revenue | 1,234,567.89 | +12.5% |\n"
        "| Ragged Row | -450.00 |\n"
        "| | empty cell test | |\n"
    )
    result = OCRResult(
        file_path="messy_table.pdf",
        pages=[PageResult(page_num=1, markdown=messy_md, status=JobStatus.SUCCESS)],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "messy_table.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    assert len(reopened.tables) == 1
    table = reopened.tables[0]

    # 1. Consistent column count across all rows (max_cols = 3)
    assert len(table.columns) == 3
    for idx, row in enumerate(table.rows):
        assert len(row.cells) == 3, f"Row {idx} does not have consistent 3 columns"

    # 2. Escaped pipe handling in header
    header_cell_0 = table.rows[0].cells[0].text
    assert "|" in header_cell_0, "Escaped pipe must be unescaped to literal '|'"
    assert "Metric | Name" in header_cell_0

    # 3. Numeric formatting verbatim preservation (decimals, commas, negative, percentage)
    row_1_val = table.rows[1].cells[1].text
    assert row_1_val == "1,234,567.89", f"Expected '1,234,567.89', got '{row_1_val}'"
    row_1_pct = table.rows[1].cells[2].text
    assert row_1_pct == "+12.5%"

    row_2_val = table.rows[2].cells[1].text
    assert row_2_val == "-450.00"

    # 4. Ragged row padding (row 2 was missing 3rd column, must be padded with empty cell)
    assert table.rows[2].cells[2].text == "", "Ragged row missing cell must be padded with empty string"

    # 5. Empty cells handling (row 3 has empty cells)
    assert table.rows[3].cells[0].text == "", "First cell of row 3 must be empty"
    assert table.rows[3].cells[1].text == "empty cell test"
    assert table.rows[3].cells[2].text == "", "Third cell of row 3 must be empty"


# ==============================================================================
# Requirement 3: Headings, Text Formatting, & Lists
# ==============================================================================

def test_headings_mapping(tmp_path: Path) -> None:
    """Requirement 3: Verify #, ##, ### map to Heading 1, Heading 2, Heading 3."""
    md = "# Main Title\n\n## Sub Section\n\n### Detail Level"
    result = OCRResult(
        file_path="headings.pdf",
        pages=[PageResult(page_num=1, markdown=md, status=JobStatus.SUCCESS)],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "headings.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    paragraphs = reopened.paragraphs

    assert paragraphs[0].text == "Main Title"
    assert paragraphs[0].style is not None
    assert paragraphs[0].style.name == "Heading 1"

    assert paragraphs[1].text == "Sub Section"
    assert paragraphs[1].style is not None
    assert paragraphs[1].style.name == "Heading 2"

    assert paragraphs[2].text == "Detail Level"
    assert paragraphs[2].style is not None
    assert paragraphs[2].style.name == "Heading 3"


def test_bold_italic_and_lists(tmp_path: Path) -> None:
    """Requirement 3: Verify bold/italic run formatting and bullet/numbered list styles."""
    md = (
        "Text with **bold words** and *italic words*.\n\n"
        "- Bullet item 1\n"
        "- Bullet item 2\n\n"
        "1. First numbered\n"
        "2. Second numbered\n"
    )
    result = OCRResult(
        file_path="formatting.pdf",
        pages=[PageResult(page_num=1, markdown=md, status=JobStatus.SUCCESS)],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "formatting.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    paragraphs = reopened.paragraphs

    # Paragraph 0: bold and italic runs
    p0 = paragraphs[0]
    runs = p0.runs
    bold_runs = [r for r in runs if r.bold]
    italic_runs = [r for r in runs if r.italic]
    assert any("bold words" in r.text for r in bold_runs)
    assert any("italic words" in r.text for r in italic_runs)

    # Paragraphs 1-2: Bullet list
    assert paragraphs[1].style is not None
    assert paragraphs[1].style.name == "List Bullet"
    assert "Bullet item 1" in paragraphs[1].text
    assert paragraphs[2].style is not None
    assert paragraphs[2].style.name == "List Bullet"
    assert "Bullet item 2" in paragraphs[2].text

    # Paragraphs 3-4: Numbered list
    assert paragraphs[3].style is not None
    assert paragraphs[3].style.name == "List Number"
    assert "First numbered" in paragraphs[3].text
    assert paragraphs[4].style is not None
    assert paragraphs[4].style.name == "List Number"
    assert "Second numbered" in paragraphs[4].text


# ==============================================================================
# Requirement 4: Inline Code vs. Fenced Code Blocks & Blockquotes
# ==============================================================================

def test_inline_code_vs_fenced_code_block_distinction(tmp_path: Path) -> None:
    """Requirement 4: Verify inline code stays inline in same paragraph while fenced code is indented block."""
    md = (
        "Run the `cli.main` command with `--format` flag.\n\n"
        "```python\n"
        "def compute_total(a, b):\n"
        "    return a + b\n"
        "```\n\n"
        "> Supervised by Region Admin.\n"
    )
    result = OCRResult(
        file_path="code_distinction.pdf",
        pages=[PageResult(page_num=1, markdown=md, status=JobStatus.SUCCESS)],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "code_distinction.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    paragraphs = reopened.paragraphs

    # 1. Inline code paragraph:
    # Must NOT have left_indent set to 0.5" / 36pt (it is normal body text)
    p_inline = paragraphs[0]
    assert p_inline.paragraph_format.left_indent is None or p_inline.paragraph_format.left_indent == 0
    # Must contain runs in the SAME paragraph with Consolas font
    consolas_runs = [r for r in p_inline.runs if r.font.name == "Consolas"]
    assert len(consolas_runs) >= 2
    assert any("cli.main" in r.text for r in consolas_runs)
    assert any("--format" in r.text for r in consolas_runs)
    # The normal text runs must also be in the SAME paragraph
    assert "Run the " in p_inline.text
    assert " command with " in p_inline.text

    # 2. Fenced code block paragraph:
    # Must be a standalone block with left indentation
    p_fenced = paragraphs[1]
    assert p_fenced.paragraph_format.left_indent == Pt(36), (
        f"Fenced code must have 36pt left indent, got {p_fenced.paragraph_format.left_indent}"
    )
    assert "def compute_total(a, b):" in p_fenced.text
    assert p_fenced.runs[0].font.name == "Consolas"

    # 3. Blockquote paragraph:
    # Must be a standalone block with left indentation and monospace font
    p_quote = paragraphs[2]
    assert p_quote.paragraph_format.left_indent == Pt(36), (
        f"Blockquote must have 36pt left indent, got {p_quote.paragraph_format.left_indent}"
    )
    assert "Supervised by Region Admin." in p_quote.text
    assert p_quote.runs[0].font.name == "Consolas"


# ==============================================================================
# Requirement 5: LaTeX Formula Preservation
# ==============================================================================

def test_latex_formula_raw_text_preservation(tmp_path: Path) -> None:
    """Requirement 5: Verify LaTeX math syntax ($...$ and $$...$$) is preserved verbatim as plain text."""
    latex_md = (
        "Inline formula: $E = mc^2$ and $x_{1,2} = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$.\n\n"
        "Block equation: $$\\sum_{i=1}^n x_i = X$$\n"
    )
    result = OCRResult(
        file_path="latex.pdf",
        pages=[PageResult(page_num=1, markdown=latex_md, status=JobStatus.SUCCESS)],
        status=JobStatus.SUCCESS,
    )

    doc = build_docx(result)
    target = tmp_path / "latex.docx"
    doc.save(str(target))

    reopened = Document(str(target))
    paragraphs = reopened.paragraphs

    # Verify inline formulas remain verbatim strings with dollar signs
    p0_text = paragraphs[0].text
    assert "$E = mc^2$" in p0_text
    assert "$x_{1,2} = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$" in p0_text

    # Verify block formula remains verbatim string
    p1_text = paragraphs[1].text
    assert "$$\\sum_{i=1}^n x_i = X$$" in p1_text


# ==============================================================================
# Export Helper (export_to_docx_bytes)
# ==============================================================================

def test_export_to_docx_bytes() -> None:
    """Verify export_to_docx_bytes produces valid binary buffer."""
    result = OCRResult(
        file_path="helpers.pdf",
        pages=[PageResult(page_num=1, markdown="# Test Header\nSample content.", status=JobStatus.SUCCESS)],
        status=JobStatus.SUCCESS,
    )

    data = export_to_docx_bytes(result)
    assert isinstance(data, bytes)
    assert len(data) > 0

    # Verify bytes can be loaded by Document
    doc_from_bytes = Document(io.BytesIO(data))
    assert doc_from_bytes.paragraphs[0].text == "Test Header"


def test_empty_or_failed_result_handled_cleanly() -> None:
    """Verify empty or failed OCRResult returns clean document without raising exceptions."""
    result_empty = OCRResult(file_path="empty.pdf", pages=[], status=JobStatus.FAILED)
    doc_empty = build_docx(result_empty)
    assert hasattr(doc_empty, "save")
    assert hasattr(doc_empty, "paragraphs")

    result_error = OCRResult(file_path="err.pdf", pages=[], status=JobStatus.FAILED, error="Corrupt PDF header")
    doc_err = build_docx(result_error)
    assert "Error: Corrupt PDF header" in doc_err.paragraphs[0].text
