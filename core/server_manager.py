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
import re
import shutil
import subprocess
import sys
import threading
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from config.settings import Settings

logger = logging.getLogger(__name__)

from core.hardware import get_cached_hardware_profile
from core.job_object import (
    _assign_process_to_job,
    _close_job_handle,
    _create_kill_on_close_job,
)


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


def _normalize_model_family(raw: str) -> str:
    """Extract a canonical model family name from a model ID, repo, or file path.

    Strips directory paths, repo prefixes, file extensions (.gguf, .bin),
    quantization tags (e.g. -Q8_0, .Q4_K_M), and GGUF format suffixes.

    Args:
        raw: Model ID, repo name, or file path.

    Returns:
        str: Normalized lowercase model family name.
    """
    if not raw or not isinstance(raw, str):
        return ""
    name = raw.replace("\\", "/").rstrip("/").split("/")[-1].strip().lower()
    name = re.sub(r"\.(gguf|bin)$", "", name, flags=re.IGNORECASE)
    while True:
        cleaned = re.sub(
            r"[-._](q[0-9]+[a-z0-9_]*|f16|f32|bf16|gguf)$",
            "",
            name,
            flags=re.IGNORECASE,
        )
        if cleaned and cleaned != name:
            name = cleaned
        else:
            break
    return name


def _model_matches(primary: str, expected: str) -> bool:
    """Check if primary model ID matches expected model repo or path.

    Performs case-insensitive substring, stem, and model family matching.

    Args:
        primary: Model ID reported by the running server.
        expected: Model repo or local file path expected in settings.

    Returns:
        bool: True if primary matches expected, False otherwise.
    """
    if not primary or not expected:
        return False
    p_clean = primary.strip().lower()
    e_clean = expected.strip().lower()
    if p_clean == e_clean:
        return True
    if p_clean in e_clean or e_clean in p_clean:
        return True
    p_stem = Path(primary).stem.strip().lower()
    e_stem = Path(expected).stem.strip().lower()
    if p_stem == e_stem:
        return True
    if p_stem in e_stem or e_stem in p_stem:
        return True
    p_fam = _normalize_model_family(primary)
    e_fam = _normalize_model_family(expected)
    if p_fam and e_fam:
        if p_fam == e_fam:
            return True
        if p_fam in e_fam or e_fam in p_fam:
            return True
    return False


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
        self._stopping: bool = False
        self._log_buffer: deque[str] = deque(maxlen=200)
        self._reader_thread: Optional[threading.Thread] = None
        # _lock guards state only and is held briefly. It is never held across
        # terminate()/wait()/kill() or process spawns, so the stdout reader can
        # keep draining while a lifecycle operation is in flight.
        self._lock = threading.Lock()
        # _lifecycle_lock serializes start() and stop() as whole operations. It may
        # be held across terminate()/wait()/kill() so a start() arriving mid-stop()
        # waits until the old process is dead instead of racing it for the port.
        self._lifecycle_lock = threading.Lock()
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
            if self._stopping:
                # Process is actively being terminated by stop(). Do not probe or adopt.
                return self._build_status_info_locked()

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

            endpoint = self.settings.local_endpoint
            session = self._session

        # 2. Probe endpoint outside lock
        probe_status, probe_msg = probe_server_health(
            endpoint,
            timeout=1.5,
            session=session,
        )

        # 3. Update status under lock
        with self._lock:
            if self._stopping:
                # stop() was invoked during probe; preserve stop state
                return self._build_status_info_locked()

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

    def _notify_lifecycle_change(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        """Invoke the lifecycle change callback captured under the lock.

        The caller passes a reference captured while holding the lock so the
        callback runs after the lock is released. Exceptions raised by the
        callback are swallowed to keep lifecycle transitions resilient.
        """
        if callback:
            try:
                callback()
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
        callback: Optional[Callable[[], None]] = None
        with self._lifecycle_lock:
            # Check if a compatible server is already running
            active_ep = endpoint or self.settings.local_endpoint
            cur_status, cur_msg = probe_server_health(active_ep, timeout=1.5, session=self._session)
            if cur_status in (ServerStatus.READY, ServerStatus.STARTING):
                expected = model_repo or self.settings.model_repo
                model_detail = cur_msg
                base_url = resolve_base_url(active_ep)
                try:
                    resp = self._session.get(f"{base_url}/v1/models", timeout=1.5)
                    if resp.status_code == 200:
                        data = resp.json()
                        models_data = (
                            data.get("data") or data.get("models")
                            if isinstance(data, dict)
                            else data
                        )
                        model_ids: List[str] = []
                        if isinstance(models_data, list):
                            for item in models_data:
                                if isinstance(item, dict):
                                    mid = item.get("id") or item.get("name")
                                    if mid:
                                        model_ids.append(str(mid))
                                elif isinstance(item, str) and item.strip():
                                    model_ids.append(item.strip())
                        if model_ids:
                            primary_model = model_ids[0]
                            if _model_matches(primary_model, expected):
                                model_detail = primary_model
                                logger.info(
                                    "Adopted external server at %s serving expected model: %s",
                                    active_ep,
                                    primary_model,
                                )
                            else:
                                model_detail = f"serving '{primary_model}', expected '{expected}'"
                                logger.warning(
                                    "Adopted external server at %s is serving model '%s', but settings expect '%s'",
                                    active_ep,
                                    primary_model,
                                    expected,
                                )
                        else:
                            logger.info("Server already running on %s; adopting as external", active_ep)
                    else:
                        logger.info("Server already running on %s; adopting as external", active_ep)
                except Exception:
                    logger.info("Server already running on %s; adopting as external", active_ep)

                with self._lock:
                    self._ownership = ServerOwnership.EXTERNAL
                    self._status = cur_status
                    self._last_message = f"Connected to existing server ({model_detail})"
                    callback = self.on_lifecycle_change
            else:
                with self._lock:
                    existing_proc = self._process
                if existing_proc is not None and existing_proc.poll() is None:
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

                # B6: Warn-only pre-flight check for low-VRAM GPUs (non-blocking)
                try:
                    profile = get_cached_hardware_profile(blocking=False)
                    if (
                        profile is not None
                        and profile.cuda_available
                        and profile.vram_mb is not None
                        and profile.vram_mb < 2200
                    ):
                        logger.warning(
                            "Detected %d MB VRAM on '%s', below recommended ~2.2 GB for GLM-OCR (-c 8192). "
                            "Server may encounter CUDA out-of-memory errors.",
                            profile.vram_mb,
                            profile.gpu_name or "CUDA device",
                        )
                except Exception as hw_exc:
                    logger.debug("VRAM pre-flight check skipped: %s", hw_exc)

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
                        if len(mmproj_candidates) == 1:
                            chosen_mmproj = mmproj_candidates[0]
                        else:
                            sorted_candidates = sorted(mmproj_candidates)
                            logger.info(
                                "Found %d mmproj candidates for '%s': %s",
                                len(mmproj_candidates),
                                model_path.name,
                                [c.name for c in sorted_candidates],
                            )
                            quant_match = re.search(
                                r"(q[0-9]+[a-z0-9_]*|f16|f32|bf16)",
                                model_path.stem,
                                re.IGNORECASE,
                            )
                            chosen_mmproj = sorted_candidates[0]
                            if quant_match:
                                quant_tag = quant_match.group(1).lower()
                                for c in sorted_candidates:
                                    if quant_tag in c.name.lower():
                                        chosen_mmproj = c
                                        break

                        cmd.extend(["--mmproj", str(chosen_mmproj)])
                        logger.info("Auto-detected adjacent multimodal projector for local model: %s", chosen_mmproj.name)
                    else:
                        logger.warning(
                            "Local GGUF model '%s' specified without an adjacent mmproj file (*mmproj*.gguf). "
                            "Multimodal image input will fail unless an explicit --mmproj projector is configured.",
                            repo,
                        )

                logger.info("Launching server subprocess: %s", " ".join(cmd))
                with self._lock:
                    self._log_buffer.clear()
                    self._log_buffer.append(f"[ServerManager] Starting: {' '.join(cmd)}")

                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

                proc: Optional[subprocess.Popen] = None
                job_handle: Optional[int] = None
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

                    # Attach to Windows Job Object with KILL_ON_JOB_CLOSE
                    if sys.platform == "win32" and hasattr(proc, "_handle") and proc._handle:
                        job_handle = _create_kill_on_close_job()
                        if job_handle:
                            _assign_process_to_job(job_handle, int(proc._handle))

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
                        except Exception as exc:
                            logger.debug("stdout reader stopped: %s", exc)

                    reader = threading.Thread(
                        target=_drain_stdout,
                        args=(proc,),
                        name="ServerStdoutReader",
                        daemon=True,
                    )
                    reader.start()

                    with self._lock:
                        self._process = proc
                        self._ownership = ServerOwnership.MANAGED
                        self._status = ServerStatus.STARTING
                        self._last_message = "Starting llama-server..."
                        if job_handle:
                            self._job_handle = job_handle
                        self._reader_thread = reader
                        callback = self.on_lifecycle_change

                except Exception as spawn_exc:
                    if proc is not None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        try:
                            proc.wait(timeout=2.0)
                        except Exception:
                            pass
                        if proc.stdout is not None:
                            try:
                                proc.stdout.close()
                            except Exception:
                                pass
                    if sys.platform == "win32" and job_handle is not None:
                        _close_job_handle(job_handle)
                    with self._lock:
                        self._process = None
                        self._job_handle = None
                        self._status = ServerStatus.ERROR
                        self._ownership = ServerOwnership.NONE
                        self._last_message = f"Failed to spawn server process: {spawn_exc}"
                    raise RuntimeError(f"Failed to launch llama-server: {spawn_exc}") from spawn_exc
        # Invoke the lifecycle callback outside both locks so a callback that
        # re-enters ServerManager (poll_status/get_status_info/start/stop) cannot deadlock.
        self._notify_lifecycle_change(callback)

    def stop(self) -> None:
        """Gracefully terminate the managed server process.

        SAFETY GUARANTEE:
        If the server was started externally by the user (ServerOwnership.EXTERNAL),
        this method is an intentional NO-OP and will NOT terminate the external server.
        """
        callback: Optional[Callable[[], None]] = None
        with self._lifecycle_lock:
            with self._lock:
                if self._ownership != ServerOwnership.MANAGED or self._process is None:
                    logger.info("stop() called but server is not managed; leaving untouched")
                    return

                proc = self._process
                job_handle = self._job_handle
                # Mark as stopping and clear process/ownership under the lock so poll_status()
                # does not probe or adopt the dying process, a serialized start() waits,
                # and the stdout reader thread is not blocked while waiting for termination.
                self._stopping = True
                self._process = None
                self._job_handle = None
                self._ownership = ServerOwnership.NONE
                self._status = ServerStatus.OFFLINE
                self._last_message = "Stopping server..."
                logger.info("Stopping managed server process (PID %s)...", proc.pid)
                self._log_buffer.append("[ServerManager] Stopping server process...")

            # Blocking termination runs outside self._lock (still serialized by
            # _lifecycle_lock) so _drain_stdout() keeps draining and a chatty child
            # can exit cleanly instead of filling its stdout pipe and being killed.
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
                if sys.platform == "win32" and job_handle is not None:
                    _close_job_handle(job_handle)
                with self._lock:
                    self._stopping = False
                    self._status = ServerStatus.OFFLINE
                    self._ownership = ServerOwnership.NONE
                    self._last_message = "Server stopped"
                    self._log_buffer.append("[ServerManager] Server process stopped.")
                    callback = self.on_lifecycle_change
        # Invoke the lifecycle callback outside both locks so a callback that
        # re-enters ServerManager (poll_status/get_status_info/start/stop) cannot deadlock.
        self._notify_lifecycle_change(callback)

    def shutdown(self) -> None:
        """Tear down all resources and terminate managed processes on application exit."""
        self.stop()
        if self._owns_session and self._session is not None:
            self._session.close()



