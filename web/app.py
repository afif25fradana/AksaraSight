"""FastAPI web application factory for AksaraSight."""

from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Literal, Optional, Union
import uuid

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from PIL import Image
import pypdfium2 as pdfium

from config.settings import Settings
from core.client import ServerOfflineError
from core.docx_export import export_to_docx_bytes
from core.engine import OCREngine
from core.pipeline import _PDFIUM_LOCK, is_pdf, rasterize_page
from web.orchestrator import JobState, JobStatus, WebOrchestrator
from web.security import LoopbackSecurityMiddleware

logger = logging.getLogger(__name__)


def enforce_loopback_host(host: str) -> None:
    """Validate that bind host is strictly loopback.

    Raises:
        ValueError: If host is not '127.0.0.1' or 'localhost'.
    """
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError(
            f"Binding to '{host}' is prohibited. AksaraSight Web UI strictly requires loopback "
            "binding ('127.0.0.1' or 'localhost') to enforce local-only access."
        )


def probe_page_count(path: Path) -> int:
    """Determine the number of pages in a PDF or image file."""
    if is_pdf(path):
        with _PDFIUM_LOCK:
            doc = pdfium.PdfDocument(path)
            try:
                count = len(doc)
                if count <= 0:
                    raise ValueError("Document contains 0 pages")
                return count
            finally:
                doc.close()
    else:
        with Image.open(path) as img:
            return getattr(img, "n_frames", 1)


def _acquire_instance_lock(upload_dir: Path) -> Any:
    """Acquire a non-blocking instance lock on upload_dir / '.instance.lock'.

    Returns:
        The open file handle holding the lock.

    Raises:
        BlockingIOError, OSError: If another instance currently holds the lock.
    """
    upload_dir.mkdir(parents=True, exist_ok=True)
    lock_file = open(upload_dir / ".instance.lock", "a+b")
    try:
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except (BlockingIOError, OSError):
        lock_file.close()
        raise


def _release_instance_lock(lock_file: Any) -> None:
    """Release and close the instance lock file."""
    if lock_file is None:
        return
    try:
        if hasattr(lock_file, "seek") and hasattr(lock_file, "fileno"):
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            lock_file.close()
        except OSError:
            pass


def create_app(
    settings: Optional[Settings] = None,
    engine: Optional[OCREngine] = None,
    orchestrator: Optional[WebOrchestrator] = None,
    upload_dir: Optional[Union[str, Path]] = None,
    max_upload_size: int = 104857600,
    static_dir: Optional[Union[str, Path]] = None,
    allowed_port: Optional[int] = None,
    dev_mode: bool = False,
) -> FastAPI:
    """Create and configure the FastAPI web application instance."""
    app_settings = settings or Settings()
    app_engine = engine or OCREngine(settings=app_settings)
    app_orchestrator = orchestrator or WebOrchestrator(engine=app_engine)

    dev_mode = dev_mode or os.environ.get("AKSARA_WEB_DEV_MODE", "").lower() in ("1", "true")

    target_port = allowed_port
    if target_port is None and "AKSARA_WEB_PORT" in os.environ:
        try:
            target_port = int(os.environ["AKSARA_WEB_PORT"])
        except ValueError:
            pass

    if upload_dir is not None:
        target_upload_dir = Path(upload_dir).resolve()
    elif os.environ.get("LOCALAPPDATA"):
        target_upload_dir = (Path(os.environ["LOCALAPPDATA"]) / "AksaraSight" / "web_uploads").resolve()
    else:
        target_upload_dir = (Path(tempfile.gettempdir()) / "aksarasight_web_uploads").resolve()

    target_upload_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        # Startup sweep: unlink stale upload files left from previous sessions/crashes
        active_upload_dir = getattr(app_instance.state, "upload_dir", None)
        lock_file = None
        if active_upload_dir:
            upload_path = Path(active_upload_dir)
            try:
                lock_file = _acquire_instance_lock(upload_path)
                app_instance.state.instance_lock = lock_file
            except (BlockingIOError, OSError):
                logger.warning(
                    "Concurrent web server instance detected; skipping upload directory startup sweep to protect active session files."
                )
                app_instance.state.instance_lock = None

            if app_instance.state.instance_lock is not None and upload_path.exists():
                for f in upload_path.glob("*"):
                    if f.is_file() and f.name != ".instance.lock":
                        try:
                            f.unlink()
                        except OSError as e:
                            logger.warning("Failed to clean up stale upload file %s on startup: %s", f, e)
        else:
            app_instance.state.instance_lock = None

        yield

        # Server shutdown cleanup: stop worker thread and unlink session upload files
        if hasattr(app_instance.state, "orchestrator") and app_instance.state.orchestrator:
            app_instance.state.orchestrator.stop()
        held_lock = getattr(app_instance.state, "instance_lock", None)
        if held_lock is not None and active_upload_dir and Path(active_upload_dir).exists():
            upload_path = Path(active_upload_dir)
            for f in upload_path.glob("*"):
                if f.is_file() and f.name != ".instance.lock":
                    try:
                        f.unlink()
                    except OSError as e:
                        logger.warning("Failed to cleanup upload file %s: %s", f, e)
        if held_lock is not None:
            _release_instance_lock(held_lock)
            app_instance.state.instance_lock = None
            if active_upload_dir:
                lock_path = Path(active_upload_dir) / ".instance.lock"
                if lock_path.exists():
                    try:
                        lock_path.unlink()
                    except OSError:
                        pass

    app = FastAPI(
        title="AksaraSight Web API",
        version="1.2.1",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Attach loopback-only security middleware with port pinning
    app.add_middleware(
        LoopbackSecurityMiddleware,
        allowed_port=target_port,
        dev_mode=dev_mode,
    )

    # Store references on app state
    app.state.settings = app_settings
    app.state.engine = app_engine
    app.state.orchestrator = app_orchestrator
    app.state.upload_dir = target_upload_dir
    app.state.max_upload_size = max_upload_size
    app.state.allowed_port = target_port
    app.state.dev_mode = dev_mode
    app.state.instance_lock = None

    @app.get("/health")
    async def get_health() -> Dict[str, Any]:
        """Probe local inference backend availability and return server status."""
        health_status = "running"
        err_msg: Optional[str] = None
        try:
            app_engine.verify_backend(force=True)
        except ServerOfflineError as e:
            health_status = "offline"
            err_msg = str(e)
        except Exception as e:
            health_status = "offline"
            err_msg = str(e)

        return {
            "status": health_status,
            "backend": getattr(app_settings, "backend", "llama-cpp"),
            "runtime_source": getattr(app_settings, "runtime_source", "managed"),
            "target_backend": getattr(app_settings, "target_backend", "auto"),
            "endpoint": getattr(app_settings, "local_endpoint", "http://127.0.0.1:8080/v1"),
            "error": err_msg,
        }

    @app.get("/api/documents")
    async def list_documents() -> List[Dict[str, Any]]:
        """Return in-memory snapshot of all active documents in orchestrator."""
        return app_orchestrator.get_jobs_snapshot()

    @app.post("/api/documents")
    async def upload_document(file: UploadFile = File(...)) -> Dict[str, Any]:
        """Stream upload a document, validate size limit and path safety, and return job metadata."""
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing filename")

        raw_name = Path(file.filename).name
        safe_name = re.sub(r"[^\w\.\-]", "_", raw_name)
        job_id = uuid.uuid4().hex
        target_filename = f"{job_id}_{safe_name}"
        target_path = (target_upload_dir / target_filename).resolve()

        if not target_path.is_relative_to(target_upload_dir):
            raise HTTPException(status_code=400, detail="Invalid file destination path")

        total_bytes = 0
        try:
            with open(target_path, "wb") as out_f:
                while True:
                    chunk = await file.read(64 * 1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_upload_size:
                        out_f.close()
                        if target_path.exists():
                            target_path.unlink()
                        raise HTTPException(status_code=413, detail="File exceeds upload limit")
                    out_f.write(chunk)
        except HTTPException:
            raise
        except Exception as e:
            if target_path.exists():
                target_path.unlink()
            raise HTTPException(status_code=500, detail=f"Upload write failed: {e}")

        try:
            pages = probe_page_count(target_path)
        except Exception as e:
            if target_path.exists():
                target_path.unlink()
            raise HTTPException(status_code=400, detail=f"Failed to inspect document pages: {e}")

        job = JobState(
            job_id=job_id,
            filename=file.filename,
            file_path=target_path,
            status=JobStatus.QUEUED,
            page_count=pages,
        )
        app_orchestrator.register_job(job)

        return {
            "id": job_id,
            "job_id": job_id,
            "filename": file.filename,
            "pages": pages,
            "total_pages": pages,
            "preview_url": f"/api/documents/{job_id}/pages/1/preview",
        }

    @app.get("/api/documents/{job_id}/pages/{page}/preview")
    async def get_page_preview(job_id: str, page: int) -> Response:
        """Rasterize and return a single document page as PNG bytes."""
        job = app_orchestrator.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Document job not found")

        page_idx = page - 1
        if page_idx < 0 or (job.page_count > 0 and page_idx >= job.page_count):
            raise HTTPException(status_code=404, detail="Page index out of bounds")

        try:
            png_bytes = rasterize_page(job.file_path, page_idx=page_idx)
            return Response(content=png_bytes, media_type="image/png")
        except Exception as e:
            logger.exception("Failed to rasterize preview for job %s page %s", job_id, page)
            raise HTTPException(status_code=500, detail=f"Failed to rasterize page preview: {e}")

    @app.post("/api/documents/{job_id}/extract", status_code=status.HTTP_202_ACCEPTED)
    async def extract_document(job_id: str) -> Dict[str, Any]:
        """Enqueue document extraction in the orchestrator worker."""
        job = app_orchestrator.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Document job not found")

        try:
            app_orchestrator.enqueue(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Document job not found")

        return {"message": "Extraction queued", "job_id": job_id}

    @app.post("/api/documents/{job_id}/cancel")
    async def cancel_document(job_id: str, delete_file: bool = False) -> Dict[str, Any]:
        """Cancel an in-progress or queued document extraction."""
        job = app_orchestrator.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Document job not found")

        cancelled = app_orchestrator.cancel(job_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Document job not found")

        if delete_file and job.file_path and job.file_path.exists():
            try:
                job.file_path.unlink()
            except OSError as e:
                logger.warning("Failed to cleanup file on cancel for job %s: %s", job_id, e)

        return {"message": "Extraction cancelled", "job_id": job_id}

    @app.delete("/api/documents/{job_id}")
    async def delete_document(job_id: str) -> Dict[str, Any]:
        """Delete an uploaded document, remove from orchestrator, and delete file on disk."""
        job = app_orchestrator.remove_job(job_id)

        file_deleted = False
        if job and job.file_path and job.file_path.exists():
            try:
                job.file_path.unlink()
                file_deleted = True
            except OSError as e:
                logger.warning("Failed to unlink file for job %s: %s", job_id, e)

        for f in target_upload_dir.glob(f"{job_id}_*"):
            try:
                f.unlink()
                file_deleted = True
            except OSError as e:
                logger.warning("Failed to unlink file %s: %s", f, e)

        if not job and not file_deleted:
            raise HTTPException(status_code=404, detail="Document job not found")

        return {"deleted": True, "job_id": job_id}

    @app.get("/api/documents/{job_id}/export")
    async def export_document(
        job_id: str,
        format: Literal["docx", "md", "json"] = "md",
    ) -> Response:
        """Export extracted document content as DOCX, Markdown, or JSON."""
        job = app_orchestrator.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Document job not found")

        if not job.result and not job.pages_data:
            raise HTTPException(
                status_code=400,
                detail="No extraction result available to export",
            )

        stem = Path(job.filename).stem or "extracted_document"

        if format == "docx":
            if not job.result:
                raise HTTPException(status_code=400, detail="Complete extraction result required for DOCX")
            content_bytes = export_to_docx_bytes(job.result)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            filename = f"{stem}.docx"
        elif format == "md":
            if job.result:
                text = job.result.markdown
            else:
                pages = sorted(job.pages_data.keys())
                text = "\n\n---\n\n".join(job.pages_data[p].get("text", "") for p in pages)
            content_bytes = text.encode("utf-8")
            media_type = "text/markdown; charset=utf-8"
            filename = f"{stem}.md"
        elif format == "json":
            if job.result:
                json_str = job.result.to_json()
            else:
                json_str = json.dumps(job.pages_data, indent=2)
            content_bytes = json_str.encode("utf-8")
            media_type = "application/json; charset=utf-8"
            filename = f"{stem}.json"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported export format '{format}'")

        return Response(
            content=content_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/events", response_class=EventSourceResponse)
    async def sse_events(request: Request):
        """Stream real-time orchestrator queue events over Server-Sent Events."""
        async for msg in app_orchestrator.subscribe():
            if await request.is_disconnected():
                break
            yield ServerSentEvent(event=msg["event"], data=msg["data"])

    target_static_dir = Path(static_dir) if static_dir else (Path(__file__).parent / "static")
    if target_static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(target_static_dir), html=True), name="static")

    return app
