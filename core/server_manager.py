"""Backend server lifecycle manager for local inference engines.

Provides process supervision, health status probing, and diagnostic log streaming
for local serving engines (such as llama-server.exe) without GUI dependencies.
"""

import atexit
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from config.settings import Settings

logger = logging.getLogger(__name__)

# ==============================================================================
# Windows Job Object Helpers (SEC-4.1)
# ==============================================================================
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryLimit", ctypes.c_size_t),
            ("PeakJobMemoryLimit", ctypes.c_size_t),
        ]

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JobObjectExtendedLimitInformation = 9

    def _create_kill_on_close_job() -> Optional[int]:
        """Create a Win32 Job Object configured to terminate member processes on handle close."""
        try:
            k32 = ctypes.windll.kernel32
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k32.SetInformationJobObject.restype = wintypes.BOOL
            k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

            job = k32.CreateJobObjectW(None, None)
            if not job:
                return None

            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            success = k32.SetInformationJobObject(
                job,
                _JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not success:
                k32.CloseHandle(job)
                return None
            return job
        except Exception as exc:
            logger.debug("Failed to initialize Windows Job Object: %s", exc)
            return None

    def _assign_process_to_job(job_handle: int, process_handle: int) -> bool:
        """Assign a process handle to a Win32 Job Object with non-silent warning fallback."""
        try:
            k32 = ctypes.windll.kernel32
            k32.AssignProcessToJobObject.restype = wintypes.BOOL
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            ret = k32.AssignProcessToJobObject(job_handle, process_handle)
            if not ret:
                err = k32.GetLastError()
                logger.warning(
                    "Failed to assign server process to Windows Job Object (Win32 error %d). "
                    "Falling back to standard software lifecycle hooks.",
                    err,
                )
                return False
            return True
        except Exception as exc:
            logger.warning("Error assigning process to Windows Job Object: %s", exc)
            return False

    def _close_job_handle(job_handle: int) -> None:
        """Close a Win32 Job Object handle."""
        try:
            k32 = ctypes.windll.kernel32
            k32.CloseHandle.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle(job_handle)
        except Exception:
            pass
else:
    def _create_kill_on_close_job() -> Optional[int]:
        return None

    def _assign_process_to_job(job_handle: int, process_handle: int) -> bool:
        return False

    def _close_job_handle(job_handle: int) -> None:
        pass


class ServerStatus(str, Enum):
    """Execution status of the backend inference server."""
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    READY = "READY"
    ERROR = "ERROR"


class ServerOwnership(str, Enum):
    """Ownership origin of the backend inference process."""
    NONE = "NONE"          # No server running
    MANAGED = "MANAGED"    # Spawned by our application; safe to terminate
    EXTERNAL = "EXTERNAL"  # Started externally by user; must NOT terminate on close


@dataclass
class ServerStatusInfo:
    """Snapshot representation of current server state and diagnostics."""
    status: ServerStatus
    ownership: ServerOwnership
    message: str
    endpoint: str = "http://127.0.0.1:8080/v1"
    recent_logs: List[str] = field(default_factory=list)


def resolve_base_url(endpoint: str) -> str:
    """Normalize any endpoint URL to its scheme and network location (host:port).

    Args:
        endpoint: Full or partial URL (e.g. 'http://localhost:8080/v1/chat/completions').

    Returns:
        str: Base URL (e.g. 'http://localhost:8080').
    """
    cleaned = endpoint.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path.split("/")[0]
    return f"{scheme}://{netloc}"


def probe_server_health(
    endpoint: str,
    timeout: float = 1.5,
    session: Optional[requests.Session] = None,
) -> Tuple[ServerStatus, str]:
    """Probe the health and readiness of an inference backend endpoint.

    IMPORTANT THREAD-SAFETY GUARANTEE:
    This function uses its own independent requests call (or callers pass a private,
    thread-specific Session). It NEVER shares mutable Session state with VisionClient.

    Empirically verified against llama-server (build 10930):
    - Process booting (socket not bound): requests.exceptions.ConnectionError
    - Model weights loading into VRAM: HTTP 503 {"error":{"message":"Loading model",...}}
    - Fully ready for inference: HTTP 200 {"status":"ok"}

    Args:
        endpoint: Target endpoint URL (e.g. 'http://localhost:8080/v1').
        timeout: Network timeout in seconds (default: 1.5s for fast polling).
        session: Optional dedicated Session instance. If omitted, standard requests is used.

    Returns:
        Tuple[ServerStatus, str]: Current ServerStatus and human-readable diagnostic message.
    """
    base_url = resolve_base_url(endpoint)
    health_url = f"{base_url}/health"
    models_url = f"{base_url}/v1/models"

    http_client = session if session is not None else requests

    try:
        resp = http_client.get(health_url, timeout=timeout)
        if resp.status_code == 200:
            return ServerStatus.READY, "Server is healthy and ready"
        if resp.status_code == 503:
            try:
                err_data = resp.json().get("error", {})
                msg = err_data.get("message", "Loading model")
            except Exception:
                msg = "Loading model"
            return ServerStatus.STARTING, f"Server starting: {msg}"
        if resp.status_code == 404:
            # Not llama-server native /health; fallback to standard OpenAI /v1/models
            models_resp = http_client.get(models_url, timeout=timeout)
            if models_resp.status_code == 200:
                return ServerStatus.READY, "OpenAI-compatible models endpoint ready"
            return ServerStatus.ERROR, f"Models endpoint returned HTTP {models_resp.status_code}"

        return ServerStatus.ERROR, f"Health endpoint returned HTTP {resp.status_code}"

    except requests.exceptions.ConnectionError:
        return ServerStatus.OFFLINE, "Connection refused (server not running)"
    except requests.exceptions.Timeout:
        return ServerStatus.OFFLINE, "Health check timed out"
    except requests.exceptions.RequestException as req_exc:
        return ServerStatus.ERROR, f"Network error during health check: {req_exc}"
    except Exception as exc:
        return ServerStatus.ERROR, f"Unexpected error during health check: {exc}"


class ServerManager:
    """Manages the lifecycle, health polling, and diagnostic logging for local inference servers.

    Attributes:
        settings: Application configuration.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        """Initialize the ServerManager with settings and an isolated HTTP session.

        Args:
            settings: Runtime configuration. Defaults to Settings().
            session: Optional custom requests.Session. If None, an isolated Session
                is created exclusively for this ServerManager to avoid thread contention.
        """
        self.settings = settings or Settings()
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._session = requests.Session()
            # Disable environment proxies (HTTP_PROXY/HTTPS_PROXY) to enforce local-only
            # loopback communication and prevent document exfiltration through external proxies.
            # Reconsider if authenticated/proxied remote-endpoint support is ever added.
            self._session.trust_env = False
            adapter = HTTPAdapter(pool_connections=2, pool_maxsize=2)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
            self._owns_session = True

        self._process: Optional[subprocess.Popen] = None
        self._ownership: ServerOwnership = ServerOwnership.NONE
        self._status: ServerStatus = ServerStatus.OFFLINE
        self._last_message: str = "Offline"
        self._log_buffer: deque[str] = deque(maxlen=200)
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._atexit_hook = atexit.register(self.shutdown)
        self._job_handle: Optional[int] = None
        self.on_lifecycle_change: Optional[Callable[[], None]] = None

    @property
    def status(self) -> ServerStatus:
        """Return the current cached ServerStatus."""
        return self._status

    @property
    def ownership(self) -> ServerOwnership:
        """Return the current process ownership origin."""
        return self._ownership

    @property
    def is_managed(self) -> bool:
        """Return True if the active server was spawned by this manager."""
        return self._ownership == ServerOwnership.MANAGED

    def get_status_info(self) -> ServerStatusInfo:
        """Return a structured snapshot of current server state and logs."""
        with self._lock:
            return ServerStatusInfo(
                status=self._status,
                ownership=self._ownership,
                message=self._last_message,
                endpoint=self.settings.local_endpoint,
                recent_logs=list(self._log_buffer),
            )

    def get_recent_logs(self, max_lines: int = 50) -> List[str]:
        """Return the most recent lines captured from server stdout/stderr."""
        with self._lock:
            all_logs = list(self._log_buffer)
            return all_logs[-max_lines:] if max_lines > 0 else all_logs

    def poll_status(self) -> ServerStatusInfo:
        """Query server health and process status, updating internal state.

        Thread-safe method suitable for invocation from background polling loops.

        Returns:
            ServerStatusInfo: Up-to-date server state snapshot.
        """
        with self._lock:
            # 1. Check managed subprocess if one was launched
            if self._process is not None:
                ret = self._process.poll()
                if ret is not None:
                    # Process died
                    self._process = None
                    self._ownership = ServerOwnership.NONE
                    if ret != 0:
                        self._status = ServerStatus.ERROR
                        reason = self._diagnose_failure()
                        self._last_message = f"Process exited with code {ret}: {reason}"
                    else:
                        self._status = ServerStatus.OFFLINE
                        self._last_message = "Server process exited cleanly"
                    return self._build_status_info_locked()

            # 2. Probe endpoint
            probe_status, probe_msg = probe_server_health(
                self.settings.local_endpoint,
                timeout=1.5,
                session=self._session,
            )

            if probe_status == ServerStatus.READY:
                self._status = ServerStatus.READY
                if self._process is None:
                    self._ownership = ServerOwnership.EXTERNAL
                self._last_message = probe_msg

            elif probe_status == ServerStatus.STARTING:
                self._status = ServerStatus.STARTING
                if self._process is None:
                    self._ownership = ServerOwnership.EXTERNAL
                self._last_message = probe_msg

            elif probe_status == ServerStatus.OFFLINE:
                if self._process is not None:
                    # Managed process is still booting up before opening socket
                    self._status = ServerStatus.STARTING
                    self._last_message = "Starting server process..."
                else:
                    self._status = ServerStatus.OFFLINE
                    self._ownership = ServerOwnership.NONE
                    self._last_message = "Server is stopped"

            else:  # ERROR
                self._status = ServerStatus.ERROR
                self._last_message = probe_msg

            return self._build_status_info_locked()

    def _build_status_info_locked(self) -> ServerStatusInfo:
        """Internal helper to construct ServerStatusInfo while holding self._lock."""
        return ServerStatusInfo(
            status=self._status,
            ownership=self._ownership,
            message=self._last_message,
            endpoint=self.settings.local_endpoint,
            recent_logs=list(self._log_buffer),
        )

    def _notify_lifecycle_change(self) -> None:
        """Invoke lifecycle change callback if registered."""
        if self.on_lifecycle_change:
            try:
                self.on_lifecycle_change()
            except Exception as exc:
                logger.debug("Error in on_lifecycle_change callback: %s", exc)

    def _diagnose_failure(self) -> str:
        """Analyze recent log buffer lines to diagnose the root cause of startup failure."""
        recent_text = "\n".join(list(self._log_buffer)[-25:]).lower()
        if "address already in use" in recent_text or "10048" in recent_text or "failed to bind socket" in recent_text:
            return "Port already in use by another process"
        if "failed to initialize cuda" in recent_text or "cuda driver version" in recent_text:
            return "CUDA/GPU acceleration initialization failed"
        if "failed to download" in recent_text or "404" in recent_text:
            return "Failed to download model weights from repository"
        if "out of memory" in recent_text or "cuda out of memory" in recent_text:
            return "Insufficient VRAM/system memory to load model"
        return "Process terminated unexpectedly (check server logs)"

    def start(
        self,
        server_path: Optional[str] = None,
        model_repo: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> None:
        """Spawn the local llama-server backend process if not already running.

        Args:
            server_path: Optional explicit binary path to llama-server.exe.
            model_repo: Optional Hugging Face model repository or local GGUF path.
            endpoint: Optional local endpoint override.

        Raises:
            FileNotFoundError: If the llama-server executable cannot be located.
            RuntimeError: If a managed server is already running or start fails.
        """
        with self._lock:
            # Check if a compatible server is already running
            active_ep = endpoint or self.settings.local_endpoint
            cur_status, cur_msg = probe_server_health(active_ep, timeout=1.5, session=self._session)
            if cur_status in (ServerStatus.READY, ServerStatus.STARTING):
                self._ownership = ServerOwnership.EXTERNAL
                self._status = cur_status
                self._last_message = f"Connected to existing server ({cur_msg})"
                logger.info("Server already running on %s; adopting as external", active_ep)
                self._notify_lifecycle_change()
                return

            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("A managed server process is already running.")

            # Resolve executable path (uses effective_llama_server_path to support managed runtime)
            candidate_path = server_path or self.settings.effective_llama_server_path
            if not candidate_path:
                which_path = shutil.which("llama-server")
                candidate_path = which_path

            if not candidate_path or not Path(candidate_path).is_file():
                if self.settings.runtime_mode == "managed" and not server_path:
                    backend = getattr(self.settings, "managed_backend_override", "auto")
                    raise FileNotFoundError(
                        f"Managed llama.cpp runtime is not installed for backend '{backend}'. "
                        "Open Settings to download the recommended runtime."
                    )
                if not candidate_path:
                    raise FileNotFoundError(
                        "llama-server executable path is not configured. "
                        "Configure the path to llama-server.exe in Settings."
                    )
                raise FileNotFoundError(
                    f"llama-server executable not found at '{candidate_path}'. "
                    "Configure the path to llama-server.exe in Settings."
                )

            resolved_path = str(Path(candidate_path).resolve())
            repo = model_repo or self.settings.model_repo

            # Extract port
            parsed = urlsplit(active_ep)
            port = parsed.port or 8080

            # Determine model flag: -m for local GGUF file, -hf for Hugging Face repo
            model_flag = "-m" if (Path(repo).is_file() or repo.lower().endswith(".gguf")) else "-hf"

            # Verified optimal hardware arguments
            cmd = [
                resolved_path,
                model_flag, repo,
                "--host", "127.0.0.1",
                "--port", str(port),
                "-ngl", "99",
                "-c", "8192",
                "--parallel", "1",
            ]

            # For local GGUF model files, auto-detect adjacent mmproj or emit helpful warning
            if model_flag == "-m":
                model_path = Path(repo).resolve()
                mmproj_candidates: List[Path] = []
                if model_path.parent.is_dir():
                    for p in model_path.parent.iterdir():
                        if p.is_file() and p.suffix.lower() == ".gguf" and "mmproj" in p.name.lower():
                            mmproj_candidates.append(p)

                if mmproj_candidates:
                    chosen_mmproj = sorted(mmproj_candidates)[0]
                    cmd.extend(["--mmproj", str(chosen_mmproj)])
                    logger.info("Auto-detected adjacent multimodal projector for local model: %s", chosen_mmproj.name)
                else:
                    logger.warning(
                        "Local GGUF model '%s' specified without an adjacent mmproj file (*mmproj*.gguf). "
                        "Multimodal image input will fail unless an explicit --mmproj projector is configured.",
                        repo,
                    )

            logger.info("Launching server subprocess: %s", " ".join(cmd))
            self._log_buffer.clear()
            self._log_buffer.append(f"[ServerManager] Starting: {' '.join(cmd)}")

            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                    cwd=str(Path(resolved_path).parent),
                )
                self._process = proc
                self._ownership = ServerOwnership.MANAGED
                self._status = ServerStatus.STARTING
                self._last_message = "Starting llama-server..."

                # Attach to Windows Job Object with KILL_ON_JOB_CLOSE (SEC-4.1)
                if sys.platform == "win32" and hasattr(proc, "_handle") and proc._handle:
                    self._job_handle = _create_kill_on_close_job()
                    if self._job_handle:
                        _assign_process_to_job(self._job_handle, int(proc._handle))

                # Start non-blocking stdout reader thread
                def _drain_stdout(p: subprocess.Popen) -> None:
                    if p.stdout is None:
                        return
                    try:
                        for line in p.stdout:
                            cleaned = line.rstrip("\r\n")
                            if cleaned:
                                with self._lock:
                                    self._log_buffer.append(cleaned)
                    except Exception:
                        pass

                reader = threading.Thread(
                    target=_drain_stdout,
                    args=(proc,),
                    name="ServerStdoutReader",
                    daemon=True,
                )
                reader.start()
                self._reader_thread = reader
                self._notify_lifecycle_change()

            except Exception as spawn_exc:
                self._status = ServerStatus.ERROR
                self._ownership = ServerOwnership.NONE
                self._last_message = f"Failed to spawn server process: {spawn_exc}"
                raise RuntimeError(f"Failed to launch llama-server: {spawn_exc}") from spawn_exc

    def stop(self) -> None:
        """Gracefully terminate the managed server process.

        SAFETY GUARANTEE:
        If the server was started externally by the user (ServerOwnership.EXTERNAL),
        this method is an intentional NO-OP and will NOT terminate the external server.
        """
        with self._lock:
            if self._ownership != ServerOwnership.MANAGED or self._process is None:
                logger.info("stop() called but server is not managed; leaving untouched")
                return

            proc = self._process
            logger.info("Stopping managed server process (PID %s)...", proc.pid)
            self._log_buffer.append("[ServerManager] Stopping server process...")

            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    logger.warning("Server process did not exit within 3s, killing...")
                    proc.kill()
                    proc.wait(timeout=2.0)
            except Exception as stop_exc:
                logger.warning("Error stopping server process: %s", stop_exc)
            finally:
                if sys.platform == "win32" and self._job_handle is not None:
                    _close_job_handle(self._job_handle)
                    self._job_handle = None
                self._process = None
                self._ownership = ServerOwnership.NONE
                self._status = ServerStatus.OFFLINE
                self._last_message = "Server stopped"
                self._log_buffer.append("[ServerManager] Server process stopped.")
                self._notify_lifecycle_change()

    def shutdown(self) -> None:
        """Tear down all resources and terminate managed processes on application exit."""
        self.stop()
        if self._owns_session and self._session is not None:
            self._session.close()



