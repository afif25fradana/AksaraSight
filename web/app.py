"""FastAPI application for AksaraSight Web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
import uuid
from typing import Any, AsyncIterator, Dict

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.responses import JSONResponse
from PIL import Image
import pypdfium2.raw as pdfium_c

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
