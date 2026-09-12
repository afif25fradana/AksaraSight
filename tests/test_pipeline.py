"""Unit tests for core/pipeline.py."""

import io
from pathlib import Path
from PIL import Image
import pypdfium2 as pdfium
import pytest

from core.pipeline import (
    CorruptDocumentError,
    EmptyDocumentError,
    EncryptedDocumentError,
    ExtractedPage,
    FilePreflightError,
    PipelineError,
    UnsupportedFormatError,
    check_preflight,
    image_to_base64_url,
    ingest,
    is_pdf,
)

# Minimal valid PDF containing 0 pages (empty kids list)
MINIMAL_ZERO_PAGE_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [] /Count 0 >>
endobj
xref
0 3
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
trailer
<< /Size 3 /Root 1 0 R >>
startxref
110
%%EOF"""

# Minimal standard-encrypted PDF (triggers FPDF_ERR_PASSWORD = 4)
MINIMAL_ENCRYPTED_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [] /Count 0 >>
endobj
3 0 obj
<< /Filter /Standard /V 1 /R 2 /O (12345678901234567890123456789012) /U (12345678901234567890123456789012) /P -4 >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000109 00000 n 
trailer
<< /Size 4 /Root 1 0 R /Encrypt 3 0 R >>
startxref
225
%%EOF"""


# ==============================================================================
# Pre-Flight Checks
# ==============================================================================

def test_preflight_nonexistent_file(tmp_path):
    """Verify preflight rejects missing file path."""
    missing = tmp_path / "nonexistent.png"
    with pytest.raises(FilePreflightError, match="File not found"):
        check_preflight(missing)


def test_preflight_directory_target(tmp_path):
    """Verify preflight rejects directories."""
    dir_target = tmp_path / "somedir"
    dir_target.mkdir()
    with pytest.raises(FilePreflightError, match="Target is not a regular file"):
        check_preflight(dir_target)


def test_preflight_zero_byte_path(tmp_path):
    """Verify preflight rejects 0-byte file on disk."""
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")
    with pytest.raises(FilePreflightError, match="File is empty"):
        check_preflight(empty_file)


def test_preflight_zero_byte_buffer():
    """Verify preflight rejects 0-byte in-memory buffer."""
    with pytest.raises(FilePreflightError, match="Input byte buffer is empty"):
        check_preflight(b"")


def test_preflight_invalid_input_type():
    """Verify preflight rejects unsupported types."""
    with pytest.raises(TypeError, match="Unsupported input type"):
        check_preflight(12345)  # type: ignore


def test_preflight_valid_path(tmp_path):
    """Verify preflight passes on readable non-empty file."""
    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("content", encoding="utf-8")
    check_preflight(valid_file)  # No exception raised


def test_preflight_valid_bytes():
    """Verify preflight passes on non-empty byte buffer."""
    check_preflight(b"non-empty bytes")  # No exception raised


# ==============================================================================
# Helper Functions (is_pdf, image_to_base64_url)
# ==============================================================================

def test_is_pdf_detection(tmp_path):
    """Verify is_pdf identifies files by extension and magic bytes."""
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 header")
    assert is_pdf(pdf_path) is True

    # PDF with non-pdf extension but magic bytes
    disguised = tmp_path / "doc.bin"
    disguised.write_bytes(b"%PDF-1.7 header")
    assert is_pdf(disguised) is True

    # Image file
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert is_pdf(img_path) is False

    # Bytes input
    assert is_pdf(b"%PDF-1.4 content") is True
    assert is_pdf(b"\xff\xd8\xff\xe0") is False


def test_image_to_base64_url():
    """Verify image conversion to RFC-2397 base64 data URL in RGB mode."""
    # RGBA image should be converted to RGB for JPEG
    img = Image.new("RGBA", (10, 10), color=(255, 0, 0, 128))
    url = image_to_base64_url(img, img_format="JPEG", quality=90)
    assert url.startswith("data:image/jpeg;base64,")

    # PNG format
    url_png = image_to_base64_url(img, img_format="PNG")
    assert url_png.startswith("data:image/png;base64,")


# ==============================================================================
# Ingestion: Images
# ==============================================================================

def test_ingest_valid_png(tmp_path):
    """Verify ingestion of a valid PNG image."""
    img_path = tmp_path / "test.png"
    img = Image.new("RGB", (100, 80), color="blue")
    img.save(img_path, format="PNG")

    pages = list(ingest(img_path))
    assert len(pages) == 1
    assert pages[0].page_num == 1
    assert pages[0].is_success is True
    assert pages[0].width == 100
    assert pages[0].height == 80
    assert pages[0].image_b64.startswith("data:image/jpeg;base64,")


def test_ingest_valid_jpeg_from_bytes():
    """Verify ingestion of JPEG from in-memory bytes."""
    img = Image.new("RGB", (60, 40), color="yellow")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    raw_bytes = buf.getvalue()

    pages = list(ingest(raw_bytes))
    assert len(pages) == 1
    assert pages[0].page_num == 1
    assert pages[0].is_success is True
    assert pages[0].width == 60
    assert pages[0].height == 40


def test_ingest_truncated_jpeg(tmp_path):
    """Verify truncated JPEG without EOI fails with CorruptDocumentError."""
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    raw = buf.getvalue()

    # Truncate end of image
    truncated = raw[:-25]
    trunc_path = tmp_path / "truncated.jpg"
    trunc_path.write_bytes(truncated)

    with pytest.raises(CorruptDocumentError, match="Corrupt"):
        list(ingest(trunc_path))


def test_ingest_truncated_png(tmp_path):
    """Verify truncated PNG fails with CorruptDocumentError."""
    img = Image.new("RGB", (80, 80), color="cyan")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()

    # Truncate PNG IDAT chunk
    truncated = raw[: len(raw) // 2]
    trunc_path = tmp_path / "truncated.png"
    trunc_path.write_bytes(truncated)

    with pytest.raises(CorruptDocumentError, match="Corrupt"):
        list(ingest(trunc_path))


def test_ingest_unsupported_format(tmp_path):
    """Verify non-image/non-PDF file (e.g. .docx / text) raises UnsupportedFormatError."""
    text_file = tmp_path / "notes.docx"
    text_file.write_text("PK\x03\x04 fake docx archive content", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError, match="neither a recognized image nor a PDF"):
        list(ingest(text_file))


# ==============================================================================
# Ingestion: PDFs
# ==============================================================================

def test_ingest_valid_multipage_pdf(tmp_path):
    """Verify rasterization of a valid multi-page PDF document."""
    pdf_path = tmp_path / "multipage.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(300, 400)
    doc.new_page(300, 400)
    doc.new_page(300, 400)
    doc.save(str(pdf_path))
    doc.close()

    pages = list(ingest(pdf_path, dpi=150))
    assert len(pages) == 3
    for i, page in enumerate(pages, start=1):
        assert page.page_num == i
        assert page.is_success is True
        assert page.image_b64.startswith("data:image/jpeg;base64,")
        assert page.error is None


def test_ingest_corrupt_pdf(tmp_path):
    """Verify genuinely corrupt PDF raises CorruptDocumentError."""
    corrupt_path = tmp_path / "bad.pdf"
    corrupt_path.write_bytes(b"%PDF-1.4\ncorrupted garbage xref %%EOF")

    with pytest.raises(CorruptDocumentError, match="Corrupt PDF document"):
        list(ingest(corrupt_path))


def test_ingest_encrypted_pdf(tmp_path):
    """Verify password-protected PDF raises EncryptedDocumentError."""
    enc_path = tmp_path / "encrypted.pdf"
    enc_path.write_bytes(MINIMAL_ENCRYPTED_PDF)

    with pytest.raises(EncryptedDocumentError, match="Password-protected PDF"):
        list(ingest(enc_path))


def test_ingest_zero_page_pdf(tmp_path):
    """Verify valid PDF structure with 0 pages raises EmptyDocumentError."""
    zero_page_path = tmp_path / "zero_pages.pdf"
    zero_page_path.write_bytes(MINIMAL_ZERO_PAGE_PDF)

    with pytest.raises(EmptyDocumentError, match="0 pages"):
        list(ingest(zero_page_path))


# ==============================================================================
# Edge Cases: Misnamed Extensions
# ==============================================================================

def test_ingest_mislabeled_image_as_pdf(tmp_path):
    """Verify image misnamed with .pdf extension falls back to image processing."""
    img = Image.new("RGB", (120, 90), color="magenta")
    fake_pdf = tmp_path / "real_image.pdf"
    img.save(fake_pdf, format="JPEG")

    # Should detect format error in pdfium, fall back to Pillow, and succeed
    pages = list(ingest(fake_pdf))
    assert len(pages) == 1
    assert pages[0].page_num == 1
    assert pages[0].is_success is True
    assert pages[0].width == 120
    assert pages[0].height == 90


def test_ingest_mislabeled_garbage_as_pdf(tmp_path):
    """Verify arbitrary binary with .pdf extension fails as CorruptDocumentError."""
    fake_pdf = tmp_path / "garbage.pdf"
    fake_pdf.write_bytes(b"This is completely arbitrary text, not PDF or image")

    with pytest.raises(CorruptDocumentError, match="Corrupt PDF document"):
        list(ingest(fake_pdf))


def test_ingest_mislabeled_pdf_as_image(tmp_path):
    """Verify genuine PDF with non-.pdf extension (.jpg) routes via magic bytes to PDF processor."""
    fake_img_path = tmp_path / "document.jpg"
    doc = pdfium.PdfDocument.new()
    doc.new_page(250, 350)
    doc.new_page(250, 350)
    doc.save(str(fake_img_path))
    doc.close()

    # is_pdf() should inspect magic bytes (%PDF), route to _process_pdf, and yield 2 pages
    pages = list(ingest(fake_img_path, dpi=150))
    assert len(pages) == 2
    assert pages[0].page_num == 1
    assert pages[1].page_num == 2
    assert pages[0].is_success is True
    assert pages[1].is_success is True


# ==============================================================================
# Thread Safety: Concurrent PDF Ingestion
# ==============================================================================

def test_ingest_multithreaded_pdf_concurrency(tmp_path):
    """Verify concurrent calls to ingest() across multiple threads succeed without crash.

    pypdfium2 is inherently not thread-safe and terminates the process if C API calls
    are made concurrently without synchronization. core/pipeline._process_pdf synchronizes
    all calls via module-level _PDFIUM_LOCK.
    """
    import threading

    pdf_path = tmp_path / "concurrent_test.pdf"
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 200)
    doc.save(str(pdf_path))
    doc.close()

    # Also prepare a mislabeled image to verify unlocked fallback under concurrent load
    mislabeled_path = tmp_path / "mislabeled.pdf"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(mislabeled_path, format="JPEG")

    thread_count = 10
    iterations_per_thread = 5
    errors = []

    def worker(worker_id):
        try:
            for _ in range(iterations_per_thread):
                target = mislabeled_path if worker_id % 2 == 0 else pdf_path
                pages = list(ingest(target))
                assert len(pages) == 1
                assert pages[0].is_success is True
                assert pages[0].image_b64.startswith("data:image/jpeg;base64,")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []

