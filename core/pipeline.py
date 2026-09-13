"""Document ingestion, validation, and rasterization pipeline."""

import base64
from dataclasses import dataclass
import io
import os
from pathlib import Path
import threading
from typing import Iterator, Optional, Union
from PIL import Image, ImageFile, ImageSequence, UnidentifiedImageError
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

# Enforce strict rejection of truncated images
ImageFile.LOAD_TRUNCATED_IMAGES = False

# Maximum pixel threshold for rasterization safety (matches Pillow's MAX_IMAGE_PIXELS)
MAX_RASTER_PIXELS: int = getattr(Image, "MAX_IMAGE_PIXELS", 89_478_485) or 89_478_485

# Module-level lock synchronizing all pypdfium2 C API calls across threads
_PDFIUM_LOCK = threading.Lock()


# ==============================================================================
# Pipeline Exception Hierarchy
# ==============================================================================

class PipelineError(Exception):
    """Base exception for all document ingestion and pre-flight validation failures."""


class FilePreflightError(PipelineError):
    """Raised when file does not exist, permission is denied, or input is 0 bytes."""


class UnsupportedFormatError(PipelineError):
    """Raised when input format is neither a recognized image nor a PDF."""


class CorruptDocumentError(PipelineError):
    """Raised when an image or PDF contains corrupt headers or unreadable raster streams."""


class EncryptedDocumentError(PipelineError):
    """Raised when a PDF is password-protected or uses an unsupported security scheme."""


class EmptyDocumentError(PipelineError):
    """Raised when a document contains 0 pages or no rasterizable content."""


# ==============================================================================
# Pipeline Data Models
# ==============================================================================

@dataclass
class ExtractedPage:
    """Validated, rasterized document page prepared for vision model inference.

    Attributes:
        page_num: 1-indexed page sequence number.
        image_b64: RFC-2397 Data URL string (e.g. 'data:image/jpeg;base64,...').
        width: Pixel width of the rasterized page.
        height: Pixel height of the rasterized page.
        error: Descriptive error message if rendering this specific page failed.
    """

    page_num: int
    total_pages: int = 1
    image_b64: Optional[str] = None
    width: int = 0
    height: int = 0
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        """Indicate whether the page was successfully extracted and rasterized."""
        return self.error is None and self.image_b64 is not None


# ==============================================================================
# Pre-Flight and Format Verification
# ==============================================================================

def check_preflight(source: Union[str, Path, bytes, bytearray, memoryview]) -> None:
    """Verify source existence, read permissions, and non-empty status.

    Args:
        source: File path (str or Path) or raw byte buffer.

    Raises:
        FilePreflightError: If target is missing, not a file, unreadable, or 0 bytes.
        TypeError: If input is not a path or bytes-like object.
    """
    if isinstance(source, (str, Path)):
        p = Path(source).expanduser().resolve()
        if not p.exists():
            raise FilePreflightError(f"File not found: '{p}'")
        if not p.is_file():
            raise FilePreflightError(f"Target is not a regular file: '{p}'")
        if not os.access(p, os.R_OK):
            raise FilePreflightError(f"Permission denied: cannot read '{p}'")
        if p.stat().st_size == 0:
            raise FilePreflightError(f"File is empty (0 bytes): '{p}'")
        return

    if isinstance(source, (bytes, bytearray, memoryview)):
        if len(source) == 0:
            raise FilePreflightError("Input byte buffer is empty (0 bytes)")
        return

    raise TypeError(
        f"Unsupported input type '{type(source).__name__}'. Expected str, Path, or bytes."
    )


def is_pdf(source: Union[str, Path, bytes, bytearray, memoryview]) -> bool:
    """Determine whether the source represents a PDF document.

    Checks file suffix and inspecting header magic bytes (%PDF).

    Args:
        source: File path or raw bytes.

    Returns:
        bool: True if PDF signature or extension is detected.
    """
    if isinstance(source, (str, Path)):
        p = Path(source)
        if p.suffix.lower() == ".pdf":
            return True
        try:
            with open(p, "rb") as f:
                header = f.read(1024)
                return b"%PDF" in header
        except Exception:
            return False

    if isinstance(source, (bytes, bytearray, memoryview)):
        return b"%PDF" in bytes(source[:1024])

    return False


def image_to_base64_url(image: Image.Image, img_format: str = "JPEG", quality: int = 95) -> str:
    """Convert a Pillow Image to an RFC-2397 Data URL base64 string.

    Converts non-RGB images to standard RGB prior to encoding.

    Args:
        image: Pillow Image instance.
        img_format: Image encoding format ('JPEG' or 'PNG').
        quality: JPEG compression quality (1-100, default: 95).

    Returns:
        str: RFC-2397 formatted data URL (e.g. 'data:image/jpeg;base64,...').
    """
    if image.mode != "RGB":
        image = image.convert("RGB")

    buffer = io.BytesIO()
    fmt = img_format.upper()
    if fmt in ("JPEG", "JPG"):
        image.save(buffer, format="JPEG", quality=quality)
        mime = "image/jpeg"
    elif fmt == "PNG":
        image.save(buffer, format="PNG")
        mime = "image/png"
    else:
        image.save(buffer, format=fmt)
        mime = f"image/{fmt.lower()}"

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


# ==============================================================================
# Ingestion Workers
# ==============================================================================

def _process_image(
    source: Union[str, Path, bytes, bytearray, memoryview],
    image_format: str = "JPEG",
    jpeg_quality: int = 95,
    max_image_dimension: int = 2048,
) -> Iterator[ExtractedPage]:
    """Validate and extract image frames via Pillow using two-stage validation.

    Stage 1: Image.verify() to validate headers and container structures.
    Stage 2: Reopen and Image.load() to enforce full raster data decoding and
             detect mid-stream truncation.

    Args:
        source: Image file path or byte buffer.
        image_format: Target format for base64 output ('JPEG' or 'PNG').
        jpeg_quality: Quality for JPEG encoding.
        max_image_dimension: Upper limit in pixels on longest image edge (default: 2048).

    Yields:
        ExtractedPage: Page results for each valid frame.

    Raises:
        UnsupportedFormatError: If file is not an image Pillow recognizes.
        CorruptDocumentError: If headers are corrupt or raster data is truncated.
    """
    # Helper to open a fresh image stream
    def open_fresh_img() -> Image.Image:
        if isinstance(source, (bytes, bytearray, memoryview)):
            return Image.open(io.BytesIO(source))
        return Image.open(source)

    def _downscale_if_needed(image: Image.Image, max_dim: int) -> Image.Image:
        w, h = image.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            return image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return image

    # Stage 1: Header verification
    try:
        with open_fresh_img() as img_verify:
            img_verify.verify()
    except UnidentifiedImageError as e:
        filename = getattr(source, "name", str(source)) if not isinstance(source, (bytes, bytearray, memoryview)) else "<bytes>"
        raise UnsupportedFormatError(
            f"Unsupported file format for '{filename}': neither a recognized image nor a PDF ({e})"
        ) from e
    except (SyntaxError, OSError, ValueError) as e:
        raise CorruptDocumentError(f"Corrupt image structure: {e}") from e

    # Stage 2: Re-open and decode raster data to catch mid-stream truncation
    try:
        with open_fresh_img() as img:
            n_frames = getattr(img, "n_frames", 1)
            if n_frames > 1:
                # Handle multi-frame images (e.g. multi-page TIFF)
                for page_num, frame in enumerate(ImageSequence.Iterator(img), start=1):
                    try:
                        frame.load()
                        rgb_frame = frame.convert("RGB")
                        scaled_frame = _downscale_if_needed(rgb_frame, max_image_dimension)
                        b64 = image_to_base64_url(scaled_frame, img_format=image_format, quality=jpeg_quality)
                        yield ExtractedPage(
                            page_num=page_num,
                            total_pages=n_frames,
                            image_b64=b64,
                            width=scaled_frame.width,
                            height=scaled_frame.height,
                        )
                    except Exception as frame_err:
                        yield ExtractedPage(
                            page_num=page_num,
                            total_pages=n_frames,
                            error=f"Failed to rasterize frame {page_num}: {frame_err}",
                        )
            else:
                img.load()
                rgb_img = img.convert("RGB")
                scaled_img = _downscale_if_needed(rgb_img, max_image_dimension)
                b64 = image_to_base64_url(scaled_img, img_format=image_format, quality=jpeg_quality)
                yield ExtractedPage(
                    page_num=1,
                    total_pages=1,
                    image_b64=b64,
                    width=scaled_img.width,
                    height=scaled_img.height,
                )
    except (OSError, SyntaxError, ValueError) as e:
        raise CorruptDocumentError(f"Corrupt or truncated image raster stream: {e}") from e


def _process_pdf(
    source: Union[str, Path, bytes, bytearray, memoryview],
    dpi: int = 100,
    image_format: str = "JPEG",
    jpeg_quality: int = 95,
    max_image_dimension: int = 2048,
) -> Iterator[ExtractedPage]:
    """Render PDF pages to base64 images via pypdfium2.

    Error Handling & Code Diagnostics:
    - FPDF_ERR_PASSWORD (4): Password required (empirically confirmed).
    - FPDF_ERR_SECURITY (5): Unsupported security scheme/DRM (per PDFium C API fpdfview.h).
    - FPDF_ERR_SUCCESS (0) on document load failure: Empty PDF containing 0 pages.
    - FPDF_ERR_FORMAT (3): Data format error. Triggers fallback check: if the file has
      a .pdf extension but is actually a mislabeled valid image (e.g. renamed JPEG/PNG),
      it is processed as an image. If Pillow also fails, CorruptDocumentError is raised.

    Thread Safety:
    - All pypdfium2 C API calls (document load, page render, explicit close) are
      synchronized via module-level _PDFIUM_LOCK. Pillow image encoding and page yielding
      run outside the lock to allow concurrent vision inference across threads.

    Args:
        source: PDF file path or byte buffer.
        dpi: Target rasterization resolution (default: 100).
        image_format: Target format for base64 output ('JPEG' or 'PNG').
        jpeg_quality: Quality for JPEG encoding.
        max_image_dimension: Longest edge cap forwarded to image fallback if applicable.

    Yields:
        ExtractedPage: Page results for each rendered page.

    Raises:
        EncryptedDocumentError: If PDF requires password or uses unsupported security scheme.
        EmptyDocumentError: If PDF contains 0 pages.
        CorruptDocumentError: If PDF data format is corrupt.
    """
    scale = dpi / 72.0

    try:
        with _PDFIUM_LOCK:
            doc = pdfium.PdfDocument(source)
    except pdfium.PdfiumError as e:
        err_code = getattr(e, "err_code", None)

        if err_code == pdfium_c.FPDF_ERR_PASSWORD:
            raise EncryptedDocumentError(
                "Password-protected PDF: decryption password required"
            ) from e

        if err_code == pdfium_c.FPDF_ERR_SECURITY:
            raise EncryptedDocumentError(
                "Encrypted PDF: unsupported security scheme or DRM handler"
            ) from e

        if err_code == pdfium_c.FPDF_ERR_SUCCESS:
            raise EmptyDocumentError("PDF document contains 0 pages") from e

        if err_code == pdfium_c.FPDF_ERR_FORMAT:
            # Fallback for mislabeled extensions (e.g. JPEG/PNG renamed to .pdf):
            # Attempt to process via Pillow before declaring corrupt PDF.
            # Runs outside _PDFIUM_LOCK since it invokes Pillow, not pypdfium2.
            try:
                yield from _process_image(
                    source,
                    image_format=image_format,
                    jpeg_quality=jpeg_quality,
                    max_image_dimension=max_image_dimension,
                )
                return
            except (UnsupportedFormatError, CorruptDocumentError):
                raise CorruptDocumentError(
                    f"Corrupt PDF document: data format error ({e})"
                ) from e

        raise CorruptDocumentError(f"Failed to load PDF document: {e}") from e

    try:
        with _PDFIUM_LOCK:
            total_pages = len(doc)
            if total_pages == 0:
                raise EmptyDocumentError("PDF document contains 0 pages")

        for i in range(total_pages):
            page_num = i + 1
            render_error: Optional[str] = None
            pil_img: Optional[Image.Image] = None

            with _PDFIUM_LOCK:
                try:
                    page = doc[i]
                    try:
                        width_pt, height_pt = page.get_size()
                        pixel_width = int(width_pt * scale)
                        pixel_height = int(height_pt * scale)
                        pixel_area = pixel_width * pixel_height

                        if pixel_area > MAX_RASTER_PIXELS:
                            render_error = (
                                f"Page {page_num} dimensions ({pixel_width}x{pixel_height} = "
                                f"{pixel_area:,} pixels) exceed safety threshold of "
                                f"{MAX_RASTER_PIXELS:,} pixels"
                            )
                        else:
                            pil_img = page.render(scale=scale).to_pil()
                    finally:
                        page.close()
                except Exception as page_err:
                    render_error = f"Failed to rasterize page {page_num}: {page_err}"

            if render_error:
                yield ExtractedPage(
                    page_num=page_num,
                    total_pages=total_pages,
                    error=render_error,
                )
                continue

            assert pil_img is not None
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            b64 = image_to_base64_url(pil_img, img_format=image_format, quality=jpeg_quality)
            yield ExtractedPage(
                page_num=page_num,
                total_pages=total_pages,
                image_b64=b64,
                width=pil_img.width,
                height=pil_img.height,
            )
    finally:
        with _PDFIUM_LOCK:
            doc.close()


# ==============================================================================
# Public Ingestion Interface
# ==============================================================================

def ingest(
    source: Union[str, Path, bytes, bytearray, memoryview],
    dpi: int = 100,
    image_format: str = "JPEG",
    jpeg_quality: int = 95,
    max_image_dimension: int = 2048,
) -> Iterator[ExtractedPage]:
    """Ingest, validate, and rasterize a document into base64 vision API pages.

    Supports both single/multi-page images (PNG, JPEG, TIFF, etc.) and PDF documents.
    Safe to call from multiple threads concurrently (internally synchronized around
    pypdfium2 C API calls).

    Args:
        source: File path (str | Path) or in-memory byte buffer.
        dpi: PDF rasterization resolution (default: 100, recommended for GLM-OCR).
        image_format: Vision API image encoding format ('JPEG' or 'PNG').
        jpeg_quality: JPEG compression quality (default: 95).
        max_image_dimension: Longest edge resolution cap for standalone images (default: 2048).

    Yields:
        ExtractedPage: Validated, RGB base64-encoded page objects.

    Raises:
        FilePreflightError: If target file does not exist, permission is denied, or 0 bytes.
        UnsupportedFormatError: If file is neither a supported image format nor a PDF.
        CorruptDocumentError: If headers are corrupted, truncated, or unreadable.
        EncryptedDocumentError: If PDF is password-protected or uses unsupported DRM.
        EmptyDocumentError: If PDF contains 0 pages.
    """
    check_preflight(source)

    if is_pdf(source):
        yield from _process_pdf(
            source,
            dpi=dpi,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
            max_image_dimension=max_image_dimension,
        )
    else:
        yield from _process_image(
            source,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
            max_image_dimension=max_image_dimension,
        )
