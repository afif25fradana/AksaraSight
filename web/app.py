"""FastAPI web application factory for AksaraSight."""

import asyncio
from contextlib import asynccontextmanager
import dataclasses
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable, Dict, List, Literal, Optional, Union
from urllib.parse import quote
import uuid

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel
import pypdfium2 as pdfium

from config.settings import Settings
from core.client import ServerOfflineError, resolve_chat_endpoint
from core.constants import SUPPORTED_EXTENSIONS, __version__
from core.diagnostics import run_diagnostics
from core.docx_export import export_to_docx_bytes
from core.engine import OCREngine
from core.model_manager import (
    PINNED_MODEL_REPO,
    PINNED_MODEL_REVISION,
    TOTAL_MODEL_BYTES,
    get_local_model_paths,
    get_model_downloader,
)
from core.models import PROMPT_PRESETS
from core.pipeline import _PDFIUM_LOCK, is_pdf, rasterize_page
from core.server_manager import (
    ServerManager,
    ServerOwnership,
    ServerStatus,
    probe_server_health,
)
from web.orchestrator import JobState, JobStatus, WebOrchestrator
from web.security import LoopbackSecurityMiddleware

logger = logging.getLogger(__name__)

FORBIDDEN_DOWNLOAD_PARAMS = frozenset({"url", "repo", "revision", "filename", "path", "dest"})

_MAGIC_SIGNATURES: Dict[str, Callable[[bytes], bool]] = {
    ".pdf": lambda b: b"%PDF" in b[:1024],
    ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".tiff": lambda b: b.startswith(b"II*\x00") or b.startswith(b"MM\x00*"),
    ".tif": lambda b: b.startswith(b"II*\x00") or b.startswith(b"MM\x00*"),
    ".bmp": lambda b: b.startswith(b"BM"),
    ".webp": lambda b: b.startswith(b"RIFF") and len(b) >= 12 and b[8:12] == b"WEBP",
}


def validate_magic_bytes(ext: str, header: bytes) -> bool:
    """Validate that file header begins with expected magic bytes for the extension."""
    checker = _MAGIC_SIGNATURES.get(ext)
    return checker(header) if checker else False


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


MUTABLE_SETTINGS = {
    "dpi",
    "max_image_dimension",
    "max_tokens",
    "timeout",
    "max_retries",
    "auto_start_server",
    "backend",
    "runtime_mode",
    "managed_backend_override",
    "llama_server_path",
    "local_endpoint",
    "allow_remote",
    "model_repo",
}

IMMUTABLE_SETTINGS = set()


def get_safe_settings_dict(settings: Settings) -> Dict[str, Any]:
    """Extract a safe dictionary representation of application settings."""
    return {
        "backend": settings.backend,
        "local_endpoint": settings.local_endpoint,
        "runtime_mode": settings.runtime_mode,
        "managed_backend_override": settings.managed_backend_override,
        "llama_server_path": settings.llama_server_path,
        "allow_remote": settings.allow_remote,
        "dpi": settings.dpi,
        "max_image_dimension": settings.max_image_dimension,
        "max_tokens": settings.max_tokens,
        "timeout": settings.timeout,
        "max_retries": settings.max_retries,
        "auto_start_server": settings.auto_start_server,
        "model_repo": settings.model_repo,
    }


def _pick_executable_file() -> Optional[str]:
    """Spawn a subprocess with Tkinter to pick an executable file via native file dialog."""
    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        "path = filedialog.askopenfilename(\n"
        "    title='Select llama-server Executable',\n"
        "    filetypes=[('Executable files', '*.exe'), ('All files', '*.*')],\n"
        ")\n"
        "root.destroy()\n"
        "if path:\n"
        "    print(path.strip())\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            return out or None
        return None
    except Exception as exc:
        logger.warning("Native file dialog failed or cancelled: %s", exc)
        return None


class ExtractRequest(BaseModel):
    prompt_mode: Optional[str] = "text"


class OutputOpenRequest(BaseModel):
    path: Optional[str] = None


def get_output_dir(app: FastAPI) -> Path:
    """Resolve and ensure the local output directory for export artifacts."""
    target: Optional[Path] = getattr(app.state, "output_dir", None)
    if target is not None:
        p = Path(target).resolve()
    else:
        env_dir = os.getenv("OCR_OUTPUT_DIR")
        if env_dir and env_dir.strip():
            p = Path(env_dir.strip()).expanduser().resolve()
        else:
            docs_dir = Path.home() / "Documents"
            if docs_dir.exists():
                p = (docs_dir / "AksaraSight" / "output").resolve()
            else:
                p = (Path.home() / "AksaraSight" / "output").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable bytes, KB, or MB."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def create_app(
    settings: Optional[Settings] = None,
    engine: Optional[OCREngine] = None,
    orchestrator: Optional[WebOrchestrator] = None,
    server_manager: Optional[ServerManager] = None,
    upload_dir: Optional[Union[str, Path]] = None,
    max_upload_size: int = 104857600,
    static_dir: Optional[Union[str, Path]] = None,
    allowed_port: Optional[int] = None,
    dev_mode: bool = False,
    env_path: Optional[Union[str, Path]] = None,
    model_downloader: Optional[Any] = None,
    max_queue_size: Optional[int] = None,
    output_dir: Optional[Union[str, Path]] = None,
) -> FastAPI:
    env_path = env_path or os.environ.get("AKSARA_ENV_FILE")
    app_settings = settings or Settings.from_env(env_path=env_path)
    app_engine = engine or OCREngine(settings=app_settings)
    app_orchestrator = orchestrator or WebOrchestrator(
        engine=app_engine, max_queue_size=max_queue_size
    )
    app_server_manager = server_manager or ServerManager(settings=app_settings)
    app_model_downloader = model_downloader or get_model_downloader()

    if not hasattr(app_orchestrator, "_broadcast"):
        def _orchestrator_broadcast(msg: Dict[str, Any]) -> None:
            evt = msg.get("event", "message")
            d = msg.get("data", {})
            app_orchestrator.broadcast(evt, d)
        app_orchestrator._broadcast = _orchestrator_broadcast  # type: ignore[attr-defined]

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
        # Server startup check & auto-start
        if app_settings.auto_start_server:
            cur_status, _ = probe_server_health(app_settings.local_endpoint)
            if cur_status == ServerStatus.OFFLINE:
                try:
                    app_server_manager.start()
                    if app_server_manager.ownership == ServerOwnership.MANAGED:
                        app_instance.state.server_managed = True
                        logger.info("Managed llama-server started and owned by web application.")
                except Exception as exc:
                    logger.warning("Failed to auto-start managed server on web startup: %s", exc)
            else:
                app_server_manager.poll_status()
                app_instance.state.server_managed = False
                logger.info("Existing server detected on %s; adopted as external.", app_settings.local_endpoint)
        else:
            app_server_manager.poll_status()
            app_instance.state.server_managed = False

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

        if getattr(app_instance.state, "server_managed", False):
            logger.info("Web application shutting down; stopping owned managed server.")
            app_server_manager.shutdown()
        else:
            logger.info("Web application shutting down; external server left untouched.")

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
        version=__version__,
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
    app.state.server_manager = app_server_manager
    app.state.model_downloader = app_model_downloader
    app.state.server_managed = False
    app.state.upload_dir = target_upload_dir
    app.state.max_upload_size = max_upload_size
    app.state.allowed_port = target_port
    app.state.dev_mode = dev_mode
    app.state.instance_lock = None
    app.state.last_doctor_report = None
    app.state.last_model_download_status = None
    app.state.env_path = Path(env_path).resolve() if env_path is not None else None
    app.state.output_dir = Path(output_dir).resolve() if output_dir else None

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

    @app.post("/api/doctor")
    async def post_doctor() -> Dict[str, Any]:
        """Trigger diagnostic health checks and return structured report."""
        current_settings = getattr(app.state, "settings", app_settings)
        report = await asyncio.to_thread(
            run_diagnostics,
            settings=current_settings,
            allow_remote=current_settings.allow_remote,
        )

        status_str = (
            getattr(report, "summary", None)
            or ("HEALTHY" if getattr(report, "failed_checks", 0) == 0 else "UNHEALTHY")
        )
        total_checks_count = (
            getattr(report, "total_checks", None)
            or len(getattr(report, "checks", []))
        )
        report_data = {
            "status": status_str,
            "exit_code": report.exit_code,
            "total_checks": total_checks_count,
            "failed_checks": report.failed_checks,
            "checks": [
                {
                    "category": getattr(c, "category", getattr(c, "name", "")),
                    "title": getattr(c, "title", getattr(c, "name", "")),
                    "status": c.status.value if hasattr(c.status, "value") else str(c.status),
                    "details": getattr(c, "details", getattr(c, "message", None)),
                    "remediation": getattr(c, "remediation", None),
                }
                for c in report.checks
            ],
            "text": report.format_text() if hasattr(report, "format_text") else "",
        }
        app.state.last_doctor_report = report_data
        return report_data

    @app.get("/api/doctor")
    async def get_doctor() -> Any:
        """Return the latest cached diagnostic health check report."""
        report = getattr(app.state, "last_doctor_report", None)
        if report is None:
            return JSONResponse(status_code=404, content={"report": None})
        return report

    @app.get("/api/server/status")
    async def get_server_status() -> Dict[str, Any]:
        """Return execution and ownership status of backend inference server."""
        info = app_server_manager.poll_status()
        pid = None
        if app_server_manager._process and app_server_manager._process.poll() is None:
            pid = app_server_manager._process.pid
        return {
            "status": info.status.value,
            "ownership": info.ownership.value,
            "managed_by_web": bool(getattr(app.state, "server_managed", False)),
            "message": info.message,
            "endpoint": info.endpoint,
            "pid": pid,
            "recent_logs": info.recent_logs[-15:],
        }

    @app.post("/api/server/start")
    async def post_server_start() -> Dict[str, Any]:
        """Start managed backend server if offline or stopped."""
        if app_server_manager.status in (ServerStatus.READY, ServerStatus.STARTING):
            return {
                "started": False,
                "message": f"Server is already running ({app_server_manager.ownership.value})",
                "status": app_server_manager.status.value,
                "ownership": app_server_manager.ownership.value,
            }
        if app_orchestrator.is_processing():
            raise HTTPException(
                status_code=409,
                detail="Cannot start server while extraction job is in progress",
            )
        try:
            app_server_manager.start()
            if app_server_manager.ownership == ServerOwnership.MANAGED:
                app.state.server_managed = True
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to start server: {exc}")
        new_info = app_server_manager.get_status_info()
        return {
            "started": True,
            "status": new_info.status.value,
            "ownership": new_info.ownership.value,
            "message": new_info.message,
        }

    @app.post("/api/server/stop")
    async def post_server_stop() -> Dict[str, Any]:
        """Stop managed backend server if running and managed."""
        info = app_server_manager.get_status_info()
        if info.ownership == ServerOwnership.EXTERNAL:
            raise HTTPException(
                status_code=400,
                detail="Cannot stop external server; server is not managed by this application.",
            )
        if not getattr(app.state, "server_managed", False) and info.ownership != ServerOwnership.MANAGED:
            return {
                "stopped": False,
                "message": "Server is not running or not managed",
                "status": ServerStatus.OFFLINE.value,
            }
        if app_orchestrator.is_processing():
            raise HTTPException(
                status_code=409,
                detail="Cannot stop backend server while an extraction job is currently in progress.",
            )
        app_server_manager.stop()
        app.state.server_managed = False
        return {
            "stopped": True,
            "status": ServerStatus.OFFLINE.value,
            "ownership": ServerOwnership.NONE.value,
            "message": "Managed server stopped successfully",
        }

    @app.get("/api/server/logs/stream", response_class=EventSourceResponse)
    async def stream_server_logs(request: Request):
        """Stream historical and real-time backend inference logs via Server-Sent Events."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)

        def listener_callback(line: str) -> None:
            def _put() -> None:
                try:
                    queue.put_nowait(line)
                except asyncio.QueueFull:
                    pass

            try:
                loop.call_soon_threadsafe(_put)
            except RuntimeError as loop_exc:
                logger.debug("Event loop unavailable for log listener: %s", loop_exc)

        app_server_manager.add_log_listener(listener_callback)

        try:
            # Replay initial recent logs
            for line in app_server_manager.get_recent_logs(50):
                if await request.is_disconnected():
                    return
                yield ServerSentEvent(
                    event="log",
                    data={"line": line, "historical": True},
                )

            # Stream live log lines with keepalive ping
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield ServerSentEvent(
                        event="log",
                        data={"line": line, "historical": False},
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    yield ServerSentEvent(comment="ping")
        finally:
            app_server_manager.remove_log_listener(listener_callback)

    @app.post("/api/dialog/file")
    async def dialog_pick_file() -> Dict[str, Any]:
        """Open a native Windows file dialog to pick an executable file."""
        picked = await asyncio.to_thread(_pick_executable_file)
        return {"path": picked}

    @app.get("/api/settings")
    async def get_settings() -> Dict[str, Any]:
        """Return current application settings."""
        current_settings = getattr(app.state, "settings", app_settings)
        return get_safe_settings_dict(current_settings)

    @app.patch("/api/settings")
    async def patch_settings(request: Request) -> Dict[str, Any]:
        """Validate and apply mutable settings updates, persisting to .env.

        Note: 'auto_start_server' is a startup-only configuration evaluated during
        application lifespan startup; patching it updates memory and persists to .env,
        but never starts or stops a server at runtime.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        if not isinstance(body, dict) or not body:
            raise HTTPException(status_code=400, detail="Request body must be a non-empty JSON object")

        for key in body.keys():
            if key in IMMUTABLE_SETTINGS:
                raise HTTPException(
                    status_code=403,
                    detail=f"Modification of setting '{key}' is forbidden via web API.",
                )
            if key not in MUTABLE_SETTINGS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown or non-mutable setting '{key}'.",
                )

        updates: Dict[str, Any] = {}
        for key, val in body.items():
            if key == "dpi":
                if isinstance(val, bool) or not isinstance(val, int) or not (50 <= val <= 600):
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = int(val)
            elif key == "max_image_dimension":
                if isinstance(val, bool) or not isinstance(val, int) or not (256 <= val <= 8192):
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = int(val)
            elif key == "max_tokens":
                if isinstance(val, bool) or not isinstance(val, int) or not (128 <= val <= 16384):
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = int(val)
            elif key == "timeout":
                if isinstance(val, bool) or not isinstance(val, (int, float)) or not (1.0 <= float(val) <= 600.0):
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = float(val)
            elif key == "max_retries":
                if isinstance(val, bool) or not isinstance(val, int) or not (0 <= val <= 10):
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = int(val)
            elif key == "auto_start_server":
                if not isinstance(val, bool):
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = bool(val)
            elif key == "backend":
                if not isinstance(val, str) or not val.strip():
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = val.strip()
            elif key == "runtime_mode":
                if not isinstance(val, str) or not val.strip():
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = val.strip()
            elif key == "managed_backend_override":
                if not isinstance(val, str) or not val.strip():
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = val.strip()
            elif key == "llama_server_path":
                if val is None:
                    updates[key] = None
                elif isinstance(val, str):
                    stripped = val.strip()
                    updates[key] = stripped if stripped else None
                else:
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
            elif key == "model_repo":
                if not isinstance(val, str) or not val.strip():
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = val.strip()
            elif key == "local_endpoint":
                if not isinstance(val, str) or not val.strip():
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = val.strip()
            elif key == "allow_remote":
                if not isinstance(val, bool):
                    raise HTTPException(status_code=400, detail=f"Invalid value for setting '{key}'.")
                updates[key] = bool(val)

        current_settings = getattr(app.state, "settings", app_settings)
        try:
            new_settings = dataclasses.replace(current_settings, **updates)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to update settings: {e}")

        try:
            new_settings.save_to_env(env_path=getattr(app.state, "env_path", None))
        except Exception as e:
            logger.warning("Failed to save settings to .env: %s", e)

        app.state.settings = new_settings
        if hasattr(app.state, "engine") and app.state.engine:
            app.state.engine.settings = new_settings
            if hasattr(app.state.engine, "client") and app.state.engine.client:
                app.state.engine.client.settings = new_settings
                app.state.engine.client.endpoint = resolve_chat_endpoint(new_settings.local_endpoint)
            if hasattr(app.state.engine, "invalidate_backend_verification"):
                app.state.engine.invalidate_backend_verification()

        server_stopped = False
        if hasattr(app.state, "server_manager") and app.state.server_manager:
            app.state.server_manager.settings = new_settings
            server_keys = {
                "backend",
                "runtime_mode",
                "managed_backend_override",
                "llama_server_path",
                "model_repo",
                "local_endpoint",
            }
            server_config_changed = any(
                getattr(new_settings, k) != getattr(current_settings, k) for k in server_keys
            )
            if server_config_changed:
                info = app.state.server_manager.get_status_info()
                is_running_managed = (
                    getattr(app.state, "server_managed", False)
                    or info.ownership == ServerOwnership.MANAGED
                ) and app.state.server_manager.status in (ServerStatus.READY, ServerStatus.STARTING)
                if is_running_managed:
                    app.state.server_manager.stop()
                    app.state.server_managed = False
                    server_stopped = True

        return {
            "updated": True,
            "settings": get_safe_settings_dict(new_settings),
            "server_stopped": server_stopped,
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

        ext = Path(file.filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            )

        raw_name = Path(file.filename).name
        safe_name = re.sub(r"[^\w\.\-]", "_", raw_name)
        job_id = uuid.uuid4().hex
        target_filename = f"{job_id}_{safe_name}"
        target_path = (target_upload_dir / target_filename).resolve()

        if not target_path.is_relative_to(target_upload_dir):
            raise HTTPException(status_code=400, detail="Invalid file destination path")

        first_chunk = await file.read(64 * 1024)
        if not first_chunk:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if not validate_magic_bytes(ext, first_chunk):
            raise HTTPException(
                status_code=400,
                detail=f"File signature does not match expected format '{ext}'",
            )
        if len(first_chunk) > max_upload_size:
            raise HTTPException(status_code=413, detail="File exceeds upload limit")

        total_bytes = len(first_chunk)
        try:
            with open(target_path, "wb") as out_f:
                out_f.write(first_chunk)
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
            status=JobStatus.UPLOADED,
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
    async def extract_document(
        job_id: str,
        payload: Optional[ExtractRequest] = None,
    ) -> Dict[str, Any]:
        """Enqueue document extraction in the orchestrator worker."""
        job = app_orchestrator.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Document job not found")

        mode = (payload.prompt_mode if payload and payload.prompt_mode else "text").strip().lower()
        if mode not in PROMPT_PRESETS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid prompt_mode: '{mode}'. Valid modes: {list(PROMPT_PRESETS.keys())}",
            )

        try:
            app_orchestrator.enqueue(job_id, prompt_mode=mode)
        except KeyError:
            raise HTTPException(status_code=404, detail="Document job not found")
        except queue.Full:
            raise HTTPException(
                status_code=503,
                detail="Processing queue is full. Please try again later.",
                headers={"Retry-After": "5"},
            )

        return {"message": "Extraction queued", "job_id": job_id, "prompt_mode": mode}

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
        notice = (
            f"Incomplete extraction: {job.error or 'Processing failed'}"
            if job.status == JobStatus.FAILED
            else None
        )

        if format == "docx":
            if not job.result:
                raise HTTPException(status_code=400, detail="Complete extraction result required for DOCX")
            content_bytes = export_to_docx_bytes(
                job.result,
                notice=notice if job.status == JobStatus.FAILED else None,
            )
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            filename = f"{stem}.docx"
        elif format == "md":
            if job.result:
                text = job.result.markdown
            else:
                pages = sorted(job.pages_data.keys())
                text = "\n\n---\n\n".join(job.pages_data[p].get("text", "") for p in pages)
            if job.status == JobStatus.FAILED:
                text = f"*[Notice: {notice}]*\n\n---\n\n" + text
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

        out_dir = get_output_dir(app)
        try:
            (out_dir / Path(filename).name).write_bytes(content_bytes)
        except Exception as exc:
            logger.warning("Failed to persist export artifact to %s: %s", out_dir / filename, exc)

        content_disposition_filename = quote(filename)
        if content_disposition_filename != filename:
            content_disposition = f"attachment; filename*=utf-8''{content_disposition_filename}"
        else:
            safe_ascii = filename.replace('"', '\\"')
            content_disposition = f'attachment; filename="{safe_ascii}"'

        return Response(
            content=content_bytes,
            media_type=media_type,
            headers={"Content-Disposition": content_disposition},
        )

    @app.get("/api/output")
    async def list_output_files() -> Dict[str, Any]:
        """Scan output directory for exported artifacts (.docx, .md, .json) and return metadata."""
        out_dir = get_output_dir(app)
        files: List[Dict[str, Any]] = []
        candidates: List[Path] = []
        try:
            for item in out_dir.iterdir():
                if item.is_file() and item.suffix.lower() in (".docx", ".md", ".json"):
                    candidates.append(item)
        except OSError as exc:
            logger.warning("Failed to read output directory %s: %s", out_dir, exc)

        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for file in candidates:
            try:
                st = file.stat()
                suffix = file.suffix.lower()
                ftype = "docx" if suffix == ".docx" else ("json" if suffix == ".json" else "md")
                ts_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                size_str = _format_file_size(st.st_size)
                if ftype == "docx":
                    content = "Microsoft Word OpenXML (.docx) binary package on disk."
                else:
                    try:
                        raw = file.read_bytes()[:65536]
                        content = raw.decode("utf-8", errors="replace")
                    except Exception:
                        content = ""

                files.append({
                    "id": f"out-{st.st_mtime_ns}-{file.name}",
                    "filename": file.name,
                    "type": ftype,
                    "timestamp": ts_str,
                    "size": size_str,
                    "localPath": str(file.resolve()),
                    "content": content,
                })
            except OSError as exc:
                logger.warning("Failed to stat or read output file %s: %s", file, exc)

        return {"path": str(out_dir), "files": files}

    @app.post("/api/output/open")
    async def open_output_target(body: Optional[OutputOpenRequest] = None) -> Dict[str, Any]:
        """Open output directory or reveal specific export artifact in OS file manager."""
        out_dir = get_output_dir(app).resolve()
        req_path = body.path if body else None
        if req_path:
            p = Path(req_path)
            if p.is_absolute():
                target = p.resolve()
            else:
                target = (out_dir / p).resolve()
        else:
            target = out_dir

        try:
            if not target.is_relative_to(out_dir) or not target.exists():
                raise HTTPException(status_code=400, detail="Invalid target path or target does not exist.")
        except (ValueError, RuntimeError):
            raise HTTPException(status_code=400, detail="Invalid target path.")

        opened = False
        try:
            if sys.platform == "win32":
                if target.is_file():
                    subprocess.run(["explorer.exe", f"/select,{str(target)}"], check=False)
                    opened = True
                else:
                    os.startfile(target)
                    opened = True
            elif sys.platform == "darwin":
                subprocess.run(["open", str(target)], check=False)
                opened = True
            else:
                subprocess.run(["xdg-open", str(target)], check=False)
                opened = True
        except Exception as exc:
            logger.warning("Failed to open path %s: %s", target, exc)

        return {"opened": opened, "target": str(target)}

    @app.delete("/api/output/{filename}")
    async def delete_output_file(filename: str) -> Dict[str, Any]:
        """Delete an exported artifact from the output directory."""
        out_dir = get_output_dir(app).resolve()
        target = (out_dir / filename).resolve()
        try:
            if not target.is_relative_to(out_dir) or not target.exists() or not target.is_file():
                raise HTTPException(status_code=400, detail="Invalid filename or file not found.")
        except (ValueError, RuntimeError):
            raise HTTPException(status_code=400, detail="Invalid filename.")

        try:
            target.unlink()
        except OSError as exc:
            logger.warning("Failed to delete output file %s: %s", target, exc)
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {exc}")

        return {"deleted": True, "filename": filename}

    @app.get("/api/model/status")
    async def get_model_status() -> Dict[str, Any]:
        """Return pinned model weights status and active download progress."""
        downloader = getattr(app.state, "model_downloader", None) or get_model_downloader()
        local_paths = get_local_model_paths()
        status_info = downloader.get_status() if hasattr(downloader, "get_status") else {}
        return {
            "repo": PINNED_MODEL_REPO,
            "revision": PINNED_MODEL_REVISION,
            "downloaded": local_paths is not None,
            "model_path": str(local_paths[0]) if local_paths else None,
            "mmproj_path": str(local_paths[1]) if local_paths else None,
            "total_bytes": TOTAL_MODEL_BYTES,
            "is_downloading": status_info.get("is_downloading", False),
            "bytes_downloaded": status_info.get("bytes_downloaded", 0),
            "percent": status_info.get("percent", 0.0),
            "active_file": status_info.get("active_file") or status_info.get("current_file"),
            "error": status_info.get("error_message"),
        }

    @app.post("/api/model/download", status_code=status.HTTP_202_ACCEPTED)
    async def post_model_download(request: Request) -> Dict[str, Any]:
        """Initiate background download of pinned model weights with SSE progress reporting."""
        query_keys = {str(k).strip().lower() for k in request.query_params.keys()}
        if any(k in FORBIDDEN_DOWNLOAD_PARAMS for k in query_keys):
            raise HTTPException(
                status_code=400,
                detail="Client-controlled download targets are strictly prohibited",
            )

        body_bytes = await request.body()
        if body_bytes:
            try:
                body_json = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON body")

            if isinstance(body_json, dict):
                body_keys = {str(k).strip().lower() for k in body_json.keys()}
                if any(k in FORBIDDEN_DOWNLOAD_PARAMS for k in body_keys):
                    raise HTTPException(
                        status_code=400,
                        detail="Client-controlled download targets are strictly prohibited",
                    )
            elif isinstance(body_json, list):
                for item in body_json:
                    if isinstance(item, str) and item.strip().lower() in FORBIDDEN_DOWNLOAD_PARAMS:
                        raise HTTPException(
                            status_code=400,
                            detail="Client-controlled download targets are strictly prohibited",
                        )
                    elif isinstance(item, dict):
                        item_keys = {str(k).strip().lower() for k in item.keys()}
                        if any(k in FORBIDDEN_DOWNLOAD_PARAMS for k in item_keys):
                            raise HTTPException(
                                status_code=400,
                                detail="Client-controlled download targets are strictly prohibited",
                            )

        downloader = getattr(app.state, "model_downloader", None) or get_model_downloader()
        if getattr(downloader, "is_downloading", False):
            raise HTTPException(
                status_code=409,
                detail="Model download is already in progress",
            )

        def on_download_progress(*args: Any, **kwargs: Any) -> None:
            if len(args) == 1 and isinstance(args[0], dict):
                s = args[0]
                dl = s.get("bytes_downloaded", s.get("downloaded", 0))
                tot = s.get("total_bytes", s.get("total", TOTAL_MODEL_BYTES))
                pct = s.get("percent", 0.0)
                af = s.get("active_file") or s.get("current_file", "")
                spd = s.get("speed", 0.0)
                is_dl = s.get("is_downloading", False)
                err = s.get("error_message") or s.get("error")
            elif len(args) >= 5:
                dl, tot, pct, af, spd = args[:5]
                is_dl = kwargs.get("is_downloading", True)
                err = kwargs.get("error")
            else:
                s = kwargs
                dl = s.get("bytes_downloaded", s.get("downloaded", 0))
                tot = s.get("total_bytes", s.get("total", TOTAL_MODEL_BYTES))
                pct = s.get("percent", 0.0)
                af = s.get("active_file") or s.get("current_file", "")
                spd = s.get("speed", 0.0)
                is_dl = s.get("is_downloading", True)
                err = s.get("error_message") or s.get("error")

            progress_payload = {
                "downloaded": dl,
                "total": tot,
                "percent": pct,
                "active_file": af,
                "speed": spd,
                "bytes_downloaded": dl,
                "total_bytes": tot,
                "is_downloading": is_dl,
                "error": err,
            }
            app.state.last_model_download_status = progress_payload
            payload_str = json.dumps(progress_payload)
            if hasattr(app_orchestrator, "_broadcast"):
                app_orchestrator._broadcast({"event": "model_download_progress", "data": payload_str})
            elif hasattr(app_orchestrator, "broadcast"):
                app_orchestrator.broadcast("model_download_progress", progress_payload)

        downloader.progress_callback = on_download_progress

        def _bg_download() -> None:
            try:
                downloader.download()
            except Exception as exc:
                logger.exception("Background model download encountered an error: %s", exc)

        thread = threading.Thread(
            target=_bg_download,
            daemon=True,
            name="AksaraSight-ModelDownloadWorker",
        )
        thread.start()

        return {"started": True, "message": "Model download initiated"}

    @app.post("/api/model/download/cancel")
    async def post_model_download_cancel() -> Dict[str, Any]:
        """Signal cooperative cancellation of active model download."""
        downloader = getattr(app.state, "model_downloader", None) or get_model_downloader()
        if not getattr(downloader, "is_downloading", False):
            return {"cancelled": False, "message": "No active download to cancel"}

        if hasattr(downloader, "cancel"):
            downloader.cancel()

        return {"cancelled": True, "message": "Download cancellation requested"}

    @app.get("/api/events", response_class=EventSourceResponse)
    async def sse_events(request: Request):
        """Stream real-time orchestrator queue events over Server-Sent Events."""
        async for msg in app_orchestrator.subscribe():
            if await request.is_disconnected():
                break
            event = msg.get("event", "message")
            data = msg.get("data")
            if isinstance(data, str):
                yield ServerSentEvent(event=event, raw_data=data)
            else:
                yield ServerSentEvent(event=event, data=data)

    target_static_dir = Path(static_dir) if static_dir else (Path(__file__).parent / "static")
    if target_static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(target_static_dir), html=True), name="static")

    return app
