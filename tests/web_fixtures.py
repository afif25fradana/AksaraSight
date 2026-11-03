"""Shared fixtures, mock adapters, and ASGI test runner for web API test suites."""

import asyncio
import contextlib
import io
import logging
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image

from config.settings import Settings
from core.client import ServerOfflineError
from core.models import JobConfig, JobStatus as CoreJobStatus, OCRResult, PageResult
from core.server_manager import ServerOwnership, ServerStatus, ServerStatusInfo


class AsgiClient:
    """Synchronous test client executing raw ASGI requests against FastAPI app."""

    def __init__(
        self,
        app: Any,
        server: Optional[Tuple[str, Optional[int]]] = None,
    ) -> None:
        self.app = app
        self.server = server

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
        query_string: str = "",
    ) -> Tuple[int, Dict[str, str], bytes]:
        async def _call():
            server_host = "127.0.0.1"
            pinned_port = getattr(getattr(self.app, "state", None), "allowed_port", None)
            if self.server is not None:
                server_tuple = self.server
            elif pinned_port is not None:
                server_tuple = (server_host, pinned_port)
            else:
                server_tuple = (server_host, None)

            effective_port = server_tuple[1] if (server_tuple and len(server_tuple) > 1) else None
            host_header_val = (
                f"{server_host}:{effective_port}" if effective_port is not None else "127.0.0.1:8000"
            )
            req_headers = {"host": host_header_val}
            if headers:
                req_headers.update(headers)

            headers_list = [
                (k.lower().encode("latin-1"), v.encode("latin-1"))
                for k, v in req_headers.items()
            ]

            req_path = path
            req_query = query_string
            if "?" in req_path:
                req_path, parsed_query = req_path.split("?", 1)
                if not req_query:
                    req_query = parsed_query

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.1"},
                "http_version": "1.1",
                "method": method.upper(),
                "scheme": "http",
                "path": req_path,
                "raw_path": req_path.encode("latin-1"),
                "query_string": req_query.encode("latin-1"),
                "headers": headers_list,
                "client": ("127.0.0.1", 12345),
                "server": server_tuple,
            }
            resp_headers: Dict[str, str] = {}
            resp_status = 200
            resp_body_chunks = []

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            async def send(message):
                nonlocal resp_status, resp_headers
                if message["type"] == "http.response.start":
                    resp_status = message["status"]
                    for k, v in message.get("headers", []):
                        resp_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
                elif message["type"] == "http.response.body":
                    resp_body_chunks.append(message.get("body", b""))

            await self.app(scope, receive, send)
            return resp_status, resp_headers, b"".join(resp_body_chunks)

        return asyncio.run(_call())

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        query_string: str = "",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("GET", path, headers=headers, query_string=query_string)

    def post(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("POST", path, headers=headers, body=body)

    def delete(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        query_string: str = "",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("DELETE", path, headers=headers, query_string=query_string)

    def put(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("PUT", path, headers=headers, body=body)

    def patch(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> Tuple[int, Dict[str, str], bytes]:
        return self.request("PATCH", path, headers=headers, body=body)


def _create_sample_png_bytes(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MockEngine:
    """Mock OCR engine for controlled end-to-end web testing."""

    def __init__(
        self,
        failure_mode: Optional[str] = None,
        process_gate: Optional[threading.Event] = None,
        processing_started: Optional[threading.Event] = None,
    ) -> None:
        self.failure_mode = failure_mode
        self.last_cancel_token: Optional[threading.Event] = None
        self.executed_cancel_tokens: list[Optional[threading.Event]] = []
        self.process_delay: float = 0.0
        self.process_gate = process_gate
        self.processing_started = processing_started
        self.settings: Settings = Settings()
        self.last_config: Optional[JobConfig] = None
        self.executed_configs: list[Optional[JobConfig]] = []

    def verify_backend(self, force: bool = False) -> None:
        if self.failure_mode == "offline":
            raise ServerOfflineError("Simulated offline backend")

    def process_document(
        self,
        source: Any,
        config: Optional[JobConfig] = None,
        cancel_token: Optional[threading.Event] = None,
        progress_callback: Optional[Any] = None,
    ) -> OCRResult:
        self.last_cancel_token = cancel_token
        self.executed_cancel_tokens.append(cancel_token)
        self.last_config = config
        self.executed_configs.append(config)
        if self.processing_started:
            self.processing_started.set()
        if self.process_gate:
            self.process_gate.wait()

        if self.failure_mode == "offline":
            page = PageResult(
                page_num=1,
                status=CoreJobStatus.FAILED,
                error="Simulated backend disconnect during process",
            )
            if progress_callback:
                progress_callback(1, 1, page)
            res = OCRResult(file_path=str(source), pages=[page])
            res.aborted = True
            res.status = CoreJobStatus.FAILED
            res.error = "Simulated backend disconnect during process"
            return res

        if self.process_delay > 0:
            time.sleep(self.process_delay)

        if cancel_token and cancel_token.is_set():
            res = OCRResult(file_path=str(source))
            res.cancelled = True
            res.status = CoreJobStatus.CANCELLED
            return res

        page = PageResult(
            page_num=1,
            markdown="# Test Page\n\nExtracted content from test image.",
            latency=0.15,
            status=CoreJobStatus.SUCCESS,
            raw_json={"usage": {"total_tokens": 42}},
        )

        if progress_callback:
            progress_callback(1, 1, page)

        res = OCRResult(file_path=str(source), pages=[page])
        res.status = CoreJobStatus.SUCCESS
        return res


class MockServerManager:
    """Mock ServerManager for web API testing."""

    def __init__(
        self,
        status: ServerStatus = ServerStatus.OFFLINE,
        ownership: ServerOwnership = ServerOwnership.NONE,
        message: str = "Offline",
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or Settings()
        self._status = status
        self._ownership = ownership
        self._last_message = message
        self._process = None
        self._log_buffer = ["Log line 1", "Log line 2"]
        self._log_listeners: List[Callable[[str], None]] = []
        self.start_calls = 0
        self.stop_calls = 0
        self.shutdown_calls = 0

    @property
    def status(self) -> ServerStatus:
        return self._status

    @property
    def ownership(self) -> ServerOwnership:
        return self._ownership

    def get_status_info(self) -> ServerStatusInfo:
        return ServerStatusInfo(
            status=self._status,
            ownership=self._ownership,
            message=self._last_message,
            endpoint=self.settings.local_endpoint,
            recent_logs=list(self._log_buffer),
        )

    def get_recent_logs(self, max_lines: int = 50) -> List[str]:
        return list(self._log_buffer[-max_lines:]) if max_lines > 0 else list(self._log_buffer)

    def add_log_listener(self, listener: Callable[[str], None]) -> None:
        if listener not in self._log_listeners:
            self._log_listeners.append(listener)

    def remove_log_listener(self, listener: Callable[[str], None]) -> None:
        if listener in self._log_listeners:
            self._log_listeners.remove(listener)

    def broadcast_log(self, line: str) -> None:
        self._log_buffer.append(line)
        for l in list(self._log_listeners):
            try:
                l(line)
            except Exception:
                pass

    def poll_status(self) -> ServerStatusInfo:
        return self.get_status_info()

    def start(self, **kwargs: Any) -> None:
        self.start_calls += 1
        self._status = ServerStatus.READY
        self._ownership = ServerOwnership.MANAGED
        self._last_message = "Server started"

    def stop(self) -> None:
        self.stop_calls += 1
        self._status = ServerStatus.OFFLINE
        self._ownership = ServerOwnership.NONE
        self._last_message = "Server stopped"

    def shutdown(self, timeout: Optional[float] = 2.0) -> None:
        self.shutdown_calls += 1
        self.stop()


class MockModelDownloader:
    """Mock model downloader for web API testing."""

    def __init__(
        self,
        is_downloading: bool = False,
        error_message: Optional[str] = None,
        bytes_downloaded: int = 0,
        total_bytes: int = 1434837056,
        current_file: str = "",
        percent: float = 0.0,
    ) -> None:
        self.is_downloading = is_downloading
        self.error_message = error_message
        self.bytes_downloaded = bytes_downloaded
        self.total_bytes = total_bytes
        self.current_file = current_file
        self.percent = percent
        self.download_started = threading.Event()
        self.cancel_called = threading.Event()
        self.progress_callback: Optional[Callable[..., None]] = None

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_downloading": self.is_downloading,
            "bytes_downloaded": self.bytes_downloaded,
            "total_bytes": self.total_bytes,
            "current_file": self.current_file,
            "error_message": self.error_message,
            "percent": self.percent,
        }

    def download(self) -> bool:
        self.is_downloading = True
        self.download_started.set()
        if self.cancel_called.is_set():
            self.is_downloading = False
            return False
        if self.progress_callback:
            self.progress_callback({
                "bytes_downloaded": 700000000,
                "total_bytes": self.total_bytes,
                "percent": 48.79,
                "active_file": "GLM-OCR-Q8_0.gguf",
                "speed": 10485760.0,
                "is_downloading": True,
            })
        if self.cancel_called.is_set():
            self.is_downloading = False
            return False
        self.is_downloading = False
        return True

    def cancel(self) -> None:
        self.cancel_called.set()
        self.is_downloading = False


@contextlib.contextmanager
def _isolated_frozen_logging_state():
    """Isolate root, web, and core logger handlers, levels, excepthook, and std streams during frozen logging tests."""
    root_logger = logging.getLogger()
    web_logger = logging.getLogger("web")
    core_logger = logging.getLogger("core")
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    orig_web_level = web_logger.level
    orig_core_level = core_logger.level
    original_excepthook = sys.excepthook
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    try:
        yield
    finally:
        for h in list(root_logger.handlers):
            if h not in original_handlers:
                try:
                    h.close()
                except Exception:
                    pass
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
        web_logger.setLevel(orig_web_level)
        core_logger.setLevel(orig_core_level)
        sys.excepthook = original_excepthook
        if sys.stdout is not orig_stdout and sys.stdout is not None:
            try:
                sys.stdout.close()
            except Exception:
                pass
            sys.stdout = orig_stdout
        if sys.stderr is not orig_stderr and sys.stderr is not None:
            try:
                sys.stderr.close()
            except Exception:
                pass
            sys.stderr = orig_stderr

