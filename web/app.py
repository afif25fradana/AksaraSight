"""FastAPI application for AksaraSight Web UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import io
import json
import logging
from pathlib import Path
import sys
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from core.docx_export import export_to_docx_bytes
from core.models import OCRResult, PageResult
import core.models as core_models
from core.pipeline import _PDFIUM_LOCK
from web.orchestrator import DocumentJob, JobStatus, WebOrchestrator
from web.security import (
    ALLOWED_EXTENSIONS,
    LoopbackSecurityMiddleware,
    MAX_UPLOAD_SIZE,
    generate_secure_upload_path,
    get_upload_dir,
)

logger = logging.getLogger(__name__)

orchestrator = WebOrchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle."""
    orchestrator.start()
    try:
        yield
    finally:
        orchestrator.stop()


app = FastAPI(
    title="AksaraSight Web UI API",
    version="1.3.0",
    lifespan=lifespan,
)

# Enforce loopback and host/origin verification middleware
app.add_middleware(LoopbackSecurityMiddleware)


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Loopback health probe verifying the web service is responsive."""
    return {"status": "ok", "service": "AksaraSight Web API"}


@app.post("/api/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Upload and probe an image or PDF document.

    Validates size limit, isolates file storage, probes page count,
    and registers a new DocumentJob.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension: {suffix}",
        )

    try:
        upload_path = generate_secure_upload_path(file.filename)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Read and enforce file size cap
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE // (1024 * 1024)} MB",
        )
    if len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file uploaded",
        )

    upload_path.write_bytes(contents)

    # Probe document page count
    total_pages = 1
    if suffix == ".pdf":
        try:
            enc_errhandler = "strict" if sys.platform.startswith("win32") else "surrogateescape"
            cstr_path = (str(upload_path) + "\x00").encode("utf-8", errors=enc_errhandler)
            with _PDFIUM_LOCK:
                raw_doc = pdfium_c.FPDF_LoadDocument(cstr_path, None)
                if raw_doc:
                    total_pages = max(1, pdfium_c.FPDF_GetPageCount(raw_doc))
                    pdfium_c.FPDF_CloseDocument(raw_doc)
        except Exception as e:
            logger.warning(f"Failed to probe PDF pages with PDFium: {e}")
            total_pages = 1
    else:
        try:
            with Image.open(upload_path) as img:
                total_pages = getattr(img, "n_frames", 1) or 1
        except Exception as e:
            logger.warning(f"Failed to probe image frames with Pillow: {e}")
            total_pages = 1

    job_id = uuid.uuid4().hex
    job = DocumentJob(
        job_id=job_id,
        filename=file.filename,
        file_path=upload_path,
        status=JobStatus.QUEUED,
        total_pages=total_pages,
    )
    orchestrator.register_job(job)

    return {
        "job_id": job.job_id,
        "filename": job.filename,
        "total_pages": job.total_pages,
        "status": job.status.value,
    }


@app.get("/api/documents/{job_id}/pages/{page}/preview")
async def get_page_preview(job_id: str, page: int) -> Response:
    """Render and return a PNG image preview for the specified page (1-indexed)."""
    job = orchestrator.jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if page < 1 or page > job.total_pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid page {page}. Document contains {job.total_pages} pages.",
        )

    suffix = job.file_path.suffix.lower()
    try:
        if suffix == ".pdf":
            with _PDFIUM_LOCK:
                doc = pdfium.PdfDocument(str(job.file_path))
                page_obj = doc[page - 1]
                pil_img = page_obj.render(scale=1.5).to_pil()
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                return Response(content=buf.getvalue(), media_type="image/png")
        else:
            with Image.open(job.file_path) as img:
                if hasattr(img, "seek"):
                    try:
                        img.seek(page - 1)
                    except EOFError:
                        pass
                if img.mode not in ("RGB", "L", "RGBA"):
                    pil_img = img.convert("RGB")
                else:
                    pil_img = img.copy()
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                return Response(content=buf.getvalue(), media_type="image/png")
    except Exception as exc:
        logger.exception(f"Failed to render page preview: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to render page preview: {exc}",
        )


@app.post("/api/documents/{job_id}/extract", status_code=status.HTTP_202_ACCEPTED)
async def extract_document(job_id: str) -> Dict[str, Any]:
    """Enqueue an uploaded document job for OCR processing."""
    job = orchestrator.jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    orchestrator.enqueue_job(job_id)
    return {
        "job_id": job_id,
        "status": JobStatus.QUEUED.value,
    }


@app.post("/api/documents/{job_id}/cancel")
async def cancel_document_extraction(job_id: str) -> Dict[str, Any]:
    """Cooperatively cancel an in-flight or queued document job."""
    job = orchestrator.jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    orchestrator.cancel_job(job_id)
    return {
        "job_id": job_id,
        "status": JobStatus.CANCELLED.value,
    }


@app.get("/api/documents/{job_id}/export")
async def export_document(
    job_id: str,
    format: str = Query("docx", pattern="^(docx|md|json)$"),
) -> Response:
    """Export extracted document results in DOCX, Markdown, or JSON format."""
    job = orchestrator.jobs.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if not job.pages_data and not job.result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document has not been extracted yet.",
        )

    base_stem = Path(job.filename).stem

    if format == "docx":
        if job.result:
            docx_payload = export_to_docx_bytes(job.result)
        else:
            pages = [
                PageResult(
                    page_num=p_num,
                    markdown=p_data.get("text", ""),
                    status=core_models.JobStatus.SUCCESS,
                )
                for p_num, p_data in sorted(job.pages_data.items())
            ]
            ocr_res = OCRResult(
                file_path=str(job.file_path),
                pages=pages,
                status=core_models.JobStatus.SUCCESS,
            )
            docx_payload = export_to_docx_bytes(ocr_res)

        return Response(
            content=docx_payload,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{base_stem}.docx"',
            },
        )

    elif format == "md":
        if job.result:
            md_payload = job.result.markdown
        else:
            md_payload = "\n\n---\n\n".join(
                p_data.get("text", "") for _, p_data in sorted(job.pages_data.items())
            )
        return Response(
            content=md_payload,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="{base_stem}.md"',
            },
        )

    elif format == "json":
        if job.result:
            json_payload = job.result.to_json()
        else:
            json_payload = json.dumps(
                {
                    "job_id": job.job_id,
                    "filename": job.filename,
                    "pages": job.pages_data,
                },
                indent=2,
            )
        return Response(
            content=json_payload,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{base_stem}.json"',
            },
        )

    raise HTTPException(status_code=400, detail="Invalid format")


@app.get("/api/events")
async def stream_events(request: Request) -> StreamingResponse:
    """Server-Sent Events (SSE) stream distributing live job lifecycle events."""
    loop = asyncio.get_running_loop()
    q = orchestrator.subscribe(loop)

    async def event_generator() -> AsyncIterator[str]:
        try:
            # Initial ping to verify stream connection
            yield "event: ping\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_data = await asyncio.wait_for(q.get(), timeout=15.0)
                    evt_name = event_data.get("event", "message")
                    payload = json.dumps(event_data.get("data", {}))
                    yield f"event: {evt_name}\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            orchestrator.unsubscribe((loop, q))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Mount static files directory if present (SPA support)
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
