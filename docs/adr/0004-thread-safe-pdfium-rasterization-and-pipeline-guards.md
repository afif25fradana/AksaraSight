# ADR-0004: Thread-Safe PDFium Rasterization and Pipeline Guards

## Status
Accepted

## Date
2026-10-18

## Context
Input documents vary widely in structure, page count, and quality (multi-page PDFs, high-resolution camera photos, TIFF scans, corrupt files). PDFium (`pypdfium2`) is written in C and is fundamentally not thread-safe. Unsynchronized concurrent calls cause hard process segmentation faults. In addition, high-resolution images can trigger decompression memory exhaustion (decompression bombs).

## Decision
1. Wrap all PDFium C API calls in a module-level lock (`_PDFIUM_LOCK` in `core/pipeline.py`).
2. Release the lock during subsequent Pillow downscaling and base64 encoding to allow pipeline concurrency across threads.
3. Manage `PdfBitmap` lifecycle explicitly under `_PDFIUM_LOCK`: call `bitmap.to_pil().copy()` to detach the PIL image buffer from C memory, followed by `bitmap.close()` in a `try...finally` block. This prevents Python garbage collection of `PdfBitmap` from deallocating C memory outside the mutex.
4. Encapsulate all document page probing in `core.pipeline.get_page_count()` under `_PDFIUM_LOCK`, preserving thin presentation interfaces and preventing web or CLI modules from importing PDFium directly.
5. Enforce two-stage image validation: `Image.verify()` to inspect headers, followed by reopening with `Image.load()` to catch truncated raster streams.
6. Guard against decompression bombs by checking pixel dimensions against `MAX_RASTER_PIXELS` (89,478,485 pixels) before rendering.
7. Standardize output to 100 DPI RGB JPEG base64 data URLs with a 2048px maximum dimension cap.

## Alternatives Considered & Rejected
- **Poppler / `pdf2image`**: Rejected because Poppler requires external binary installations (`pdftoppm.exe`) that cannot be cleanly packaged or resolved on Windows.
- **`PyMuPDF` (fitz)**: Rejected due to AGPL licensing restrictions, which conflict with AksaraSight's MIT license.
- **Process-level isolation for PDFium**: Rejected due to high inter-process communication (IPC) memory overhead when transferring raw bitmaps across processes on Windows.

## Consequences
- Completely eliminates C-level memory corruption and access violations during multi-threaded document processing.
- Prevents out-of-memory crashes from decompression bombs and malformed image inputs.
- Keeps presentation layers (`cli/main.py`, `web/app.py`) clean of rasterization and library locks.
- Generator-based streaming (`ingest()` yielding `ExtractedPage`) maintains a low memory footprint during multi-page document processing.
