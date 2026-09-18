"""Unit tests for core/server_manager.py."""

from collections import deque
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from config.settings import Settings
from core.server_manager import (
    ServerManager,
    ServerOwnership,
    ServerStatus,
    ServerStatusInfo,
    probe_server_health,
    resolve_base_url,
)


def test_resolve_base_url():
    """Verify endpoint string normalization to base URL."""
    assert resolve_base_url("http://localhost:8080/v1/chat/completions") == "http://localhost:8080"
    assert resolve_base_url("http://127.0.0.1:8080/v1/") == "http://127.0.0.1:8080"
    assert resolve_base_url("http://localhost:8080") == "http://localhost:8080"
    assert resolve_base_url("https://192.168.1.100:9000/v1") == "https://192.168.1.100:9000"


def test_probe_server_health_ready():
    """Verify probe returns READY on HTTP 200 {"status": "ok"}."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok"}

    with patch("requests.get", return_value=mock_resp):
        status, msg = probe_server_health("http://localhost:8080/v1")
        assert status == ServerStatus.READY
        assert "healthy" in msg


def test_probe_server_health_starting_model_loading():
    """Verify probe returns STARTING on HTTP 503 Loading model."""
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.json.return_value = {
        "error": {"message": "Loading model", "type": "unavailable_error", "code": 503}
    }

    with patch("requests.get", return_value=mock_resp):
        status, msg = probe_server_health("http://localhost:8080/v1")
        assert status == ServerStatus.STARTING
        assert "Loading model" in msg


def test_probe_server_health_openai_fallback_ready():
    """Verify probe falls back to /v1/models when /health returns 404."""
    health_resp = MagicMock()
    health_resp.status_code = 404

    models_resp = MagicMock()
    models_resp.status_code = 200
    models_resp.json.return_value = {"data": [{"id": "glm-ocr"}]}

    def _mock_get(url, **kwargs):
        if url.endswith("/health"):
            return health_resp
        if url.endswith("/models"):
            return models_resp
        return MagicMock(status_code=404)

    with patch("requests.get", side_effect=_mock_get):
        status, msg = probe_server_health("http://localhost:8080/v1")
        assert status == ServerStatus.READY
        assert "OpenAI-compatible" in msg


def test_probe_server_health_offline_connection_refused():
    """Verify ConnectionError maps to OFFLINE status."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Refused")):
        status, msg = probe_server_health("http://localhost:8080/v1")
        assert status == ServerStatus.OFFLINE
        assert "Connection refused" in msg


def test_probe_server_health_offline_timeout():
    """Verify request Timeout maps to OFFLINE status."""
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Timed out")):
        status, msg = probe_server_health("http://localhost:8080/v1")
        assert status == ServerStatus.OFFLINE
        assert "timed out" in msg


def test_probe_server_health_unexpected_status():
    """Verify unexpected HTTP error statuses map to ERROR."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("requests.get", return_value=mock_resp):
        status, msg = probe_server_health("http://localhost:8080/v1")
        assert status == ServerStatus.ERROR
        assert "HTTP 500" in msg


def test_probe_server_health_uses_independent_session():
    """Verify probe uses the session passed to it without cross-session pollution."""
    mock_session = MagicMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"status": "ok"}
    mock_session.get.return_value = mock_resp

    status, _ = probe_server_health("http://localhost:8080/v1", session=mock_session)
    assert status == ServerStatus.READY
    mock_session.get.assert_called_once()
    assert "http://localhost:8080/health" in mock_session.get.call_args[0][0]


def test_server_manager_initial_state():
    """Verify ServerManager starts in an idle, offline, unmanaged state."""
    mgr = ServerManager()
    try:
        assert mgr.status == ServerStatus.OFFLINE
        assert mgr.ownership == ServerOwnership.NONE
        assert mgr.is_managed is False
        info = mgr.get_status_info()
        assert info.status == ServerStatus.OFFLINE
        assert info.ownership == ServerOwnership.NONE
        assert info.recent_logs == []
    finally:
        mgr.shutdown()


def test_server_manager_start_missing_binary():
    """Verify start() raises FileNotFoundError if binary does not exist."""
    settings = Settings(llama_server_path=r"C:\nonexistent\llama-server.exe")
    mgr = ServerManager(settings=settings)
    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with pytest.raises(FileNotFoundError, match="llama-server executable not found"):
                mgr.start()
    finally:
        mgr.shutdown()


def test_server_manager_start_adopts_existing_external_server():
    """Verify start() adopts an already-running server without spawning a process."""
    mgr = ServerManager()
    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.READY, "Online")):
            with patch("subprocess.Popen") as mock_popen:
                mgr.start()
                mock_popen.assert_not_called()
                assert mgr.status == ServerStatus.READY
                assert mgr.ownership == ServerOwnership.EXTERNAL
                assert mgr.is_managed is False
    finally:
        mgr.shutdown()


def test_server_manager_start_spawns_managed_process(tmp_path):
    """Verify start() spawns subprocess with required flags and manages it."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_exe),
        model_repo="test-org/model-gguf",
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter(["[server] listening on 127.0.0.1:8080\n"])

    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                mgr.start()
                assert mock_popen.called
                cmd_args = mock_popen.call_args[0][0]

                assert str(fake_exe) in cmd_args[0]
                assert "-hf" in cmd_args
                assert "test-org/model-gguf" in cmd_args
                assert "--port" in cmd_args
                assert "8080" in cmd_args
                assert "-c" in cmd_args
                assert "8192" in cmd_args
                assert "--parallel" in cmd_args
                assert "1" in cmd_args

                assert mgr.status == ServerStatus.STARTING
                assert mgr.ownership == ServerOwnership.MANAGED
                assert mgr.is_managed is True
                assert mock_popen.call_args.kwargs.get("cwd") == str(fake_exe.parent)
    finally:
        mgr.shutdown()


def test_server_manager_start_spawns_with_local_gguf_flag(tmp_path):
    """Verify start() passes -m instead of -hf when model is a local .gguf file."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")
    fake_model = tmp_path / "model.gguf"
    fake_model.write_text("weights", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_exe),
        model_repo=str(fake_model),
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter([])

    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                mgr.start()
                cmd_args = mock_popen.call_args[0][0]
                assert "-m" in cmd_args
                assert str(fake_model) in cmd_args
                assert "-hf" not in cmd_args
                assert "--mmproj" not in cmd_args
                assert "--host" in cmd_args
                assert cmd_args[cmd_args.index("--host") + 1] == "127.0.0.1"
    finally:
        mgr.shutdown()


def test_server_manager_start_auto_detects_adjacent_mmproj(tmp_path):
    """Verify start() automatically detects and attaches adjacent mmproj for local GGUF."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")
    fake_model = tmp_path / "GLM-OCR-Q8_0.gguf"
    fake_model.write_text("weights", encoding="utf-8")
    fake_mmproj = tmp_path / "mmproj-GLM-OCR-Q8_0.gguf"
    fake_mmproj.write_text("vision-projector", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_exe),
        model_repo=str(fake_model),
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter([])

    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                mgr.start()
                cmd_args = mock_popen.call_args[0][0]
                assert "-m" in cmd_args
                assert str(fake_model) in cmd_args
                assert "--mmproj" in cmd_args
                mmproj_idx = cmd_args.index("--mmproj")
                assert cmd_args[mmproj_idx + 1] == str(fake_mmproj)
    finally:
        mgr.shutdown()


def test_server_manager_start_warns_when_local_gguf_missing_mmproj(tmp_path, caplog):
    """Verify start() emits a helpful warning when local GGUF lacks an adjacent mmproj."""
    import logging
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")
    fake_model = tmp_path / "custom-model.gguf"
    fake_model.write_text("weights", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_exe),
        model_repo=str(fake_model),
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter([])

    with caplog.at_level(logging.WARNING):
        try:
            with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
                with patch("subprocess.Popen", return_value=mock_proc):
                    mgr.start()
                    assert "Local GGUF model" in caplog.text
                    assert "without an adjacent mmproj file" in caplog.text
        finally:
            mgr.shutdown()


def test_server_manager_lifecycle_callback_on_start_and_stop(tmp_path):
    """Verify on_lifecycle_change callback is triggered on both start() and stop()."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_exe),
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)
    callback_mock = MagicMock()
    mgr.on_lifecycle_change = callback_mock

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter([])

    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("subprocess.Popen", return_value=mock_proc):
                mgr.start()
                assert callback_mock.call_count == 1

        mgr.stop()
        assert callback_mock.call_count == 2
    finally:
        mgr.shutdown()


def test_server_manager_registers_atexit():
    """Verify ServerManager registers an atexit shutdown hook."""
    import atexit
    mgr = ServerManager()
    try:
        assert hasattr(mgr, "_atexit_hook")
        assert mgr._atexit_hook is not None
    finally:
        mgr.shutdown()


def test_server_manager_job_object_lifecycle(tmp_path):
    """Verify ServerManager creates a Windows Job Object upon process spawn and releases it on stop (SEC-4.1)."""
    import sys
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_exe),
        model_repo="test/model",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc._handle = 1234
    mock_proc.stdout = iter([])

    with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("core.server_manager._create_kill_on_close_job", return_value=999) as mock_create_job:
                with patch("core.server_manager._assign_process_to_job", return_value=True) as mock_assign:
                    with patch("core.server_manager._close_job_handle") as mock_close_job:
                        mgr.start()
                        if sys.platform == "win32":
                            assert mock_create_job.called
                            assert mock_assign.called
                            assert mgr._job_handle == 999

                        mgr.stop()
                        if sys.platform == "win32":
                            assert mock_close_job.called
                            assert mgr._job_handle is None


def test_server_manager_stop_external_is_noop():
    """Verify stop() does NOT kill an external server."""
    mgr = ServerManager()
    try:
        mgr._ownership = ServerOwnership.EXTERNAL
        mgr._status = ServerStatus.READY
        mgr._process = None

        mgr.stop()
        # Remains external and untouched
        assert mgr.ownership == ServerOwnership.EXTERNAL
        assert mgr.status == ServerStatus.READY
    finally:
        mgr.shutdown()


def test_server_manager_stop_managed_terminates():
    """Verify stop() terminates and reaps a managed subprocess."""
    mgr = ServerManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None

    mgr._process = mock_proc
    mgr._ownership = ServerOwnership.MANAGED
    mgr._status = ServerStatus.READY

    mgr.stop()
    mock_proc.terminate.assert_called_once()
    assert mgr._process is None
    assert mgr.ownership == ServerOwnership.NONE
    assert mgr.status == ServerStatus.OFFLINE


def test_server_manager_poll_status_transitions():
    """Verify poll_status updates state correctly based on probe and process health."""
    mgr = ServerManager()
    try:
        # 1. Initially offline, no process -> OFFLINE, NONE
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            info = mgr.poll_status()
            assert info.status == ServerStatus.OFFLINE
            assert info.ownership == ServerOwnership.NONE

        # 2. Managed process alive + socket not yet listening -> STARTING, MANAGED
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mgr._process = mock_proc
        mgr._ownership = ServerOwnership.MANAGED

        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Booting")):
            info = mgr.poll_status()
            assert info.status == ServerStatus.STARTING
            assert info.ownership == ServerOwnership.MANAGED

        # 3. Managed process alive + model loading (503) -> STARTING, MANAGED
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.STARTING, "Loading")):
            info = mgr.poll_status()
            assert info.status == ServerStatus.STARTING
            assert info.ownership == ServerOwnership.MANAGED

        # 4. Managed process alive + probe returns READY -> READY, MANAGED
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.READY, "Healthy")):
            info = mgr.poll_status()
            assert info.status == ServerStatus.READY
            assert info.ownership == ServerOwnership.MANAGED

        # 5. External server found -> READY, EXTERNAL
        mgr._process = None
        mgr._ownership = ServerOwnership.NONE
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.READY, "Healthy")):
            info = mgr.poll_status()
            assert info.status == ServerStatus.READY
            assert info.ownership == ServerOwnership.EXTERNAL

    finally:
        mgr.shutdown()


def test_server_manager_poll_diagnoses_crashed_process():
    """Verify poll_status detects premature process termination and diagnoses port in use."""
    mgr = ServerManager()
    try:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited with error
        mock_proc.returncode = 1
        mgr._process = mock_proc
        mgr._ownership = ServerOwnership.MANAGED
        mgr._log_buffer.append("error: failed to bind socket: Address already in use (WSAEADDRINUSE 10048)")

        info = mgr.poll_status()
        assert info.status == ServerStatus.ERROR
        assert info.ownership == ServerOwnership.NONE
        assert "Port already in use" in info.message
    finally:
        mgr.shutdown()


def test_server_manager_log_buffer_caps_and_retrieves():
    """Verify log ring-buffer caps at 200 items and get_recent_logs returns proper slice."""
    mgr = ServerManager()
    try:
        for i in range(250):
            mgr._log_buffer.append(f"log line {i}")

        assert len(mgr._log_buffer) == 200
        assert mgr._log_buffer[0] == "log line 50"
        assert mgr._log_buffer[-1] == "log line 249"

        recent = mgr.get_recent_logs(10)
        assert len(recent) == 10
        assert recent[-1] == "log line 249"
        assert recent[0] == "log line 240"
    finally:
        mgr.shutdown()


def test_server_manager_start_managed_not_installed_raises_clear_error():
    """Verify start() raises helpful error when managed runtime is not yet installed."""
    settings = Settings(
        runtime_mode="managed",
        managed_backend_override="cpu",
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)
    try:
        with patch("core.runtime_manager.get_installed_runtime_path", return_value=None), \
             patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="Managed llama.cpp runtime is not installed for backend 'cpu'"):
                mgr.start()
    finally:
        mgr.shutdown()


def test_server_manager_start_custom_unconfigured_raises_clear_error():
    """Verify start() raises helpful error when custom path is empty or not configured."""
    settings = Settings(
        runtime_mode="custom",
        llama_server_path=None,
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)
    try:
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="llama-server executable path is not configured"):
                mgr.start()
    finally:
        mgr.shutdown()


def test_server_manager_start_managed_installed_resolves_effective_path(tmp_path):
    """Verify start() automatically resolves and invokes the installed managed runtime binary."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")

    settings = Settings(
        runtime_mode="managed",
        managed_backend_override="cpu",
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter([])

    try:
        with patch("core.runtime_manager.get_installed_runtime_path", return_value=fake_exe), \
             patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            mgr.start()
            cmd_args = mock_popen.call_args[0][0]
            assert cmd_args[0] == str(fake_exe)
    finally:
        mgr.shutdown()


def test_real_loopback_server_manager_and_vision_client_integration():
    """Verify ServerManager and VisionClient communicate cohesively across a real loopback TCP socket."""
    import http.server
    import json
    import threading
    from core.client import VisionClient

    class FakeOpenAIHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/health", "/v1/health"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            elif self.path in ("/v1/models", "/models"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data": [{"id": "GLM-OCR"}]}')
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path in ("/v1/chat/completions", "/chat/completions"):
                content_length = int(self.headers.get("Content-Length", 0))
                req_body = self.rfile.read(content_length)
                assert len(req_body) > 0

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                resp_payload = {
                    "id": "cmpl-test-loopback",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "# Extracted OCR Heading\nReal loopback content.",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
                self.wfile.write(json.dumps(resp_payload).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), FakeOpenAIHandler)
    server_port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        endpoint = f"http://127.0.0.1:{server_port}/v1"
        settings = Settings(
            local_endpoint=endpoint,
            model_repo="ggml-org/GLM-OCR-GGUF",
            timeout=5.0,
            max_retries=1,
        )

        # 1. Test ServerManager status polling against real loopback socket
        sm = ServerManager(settings=settings)
        try:
            status_info = sm.poll_status()
            assert status_info.status == ServerStatus.READY
            assert "ready" in status_info.message.lower()
        finally:
            sm.shutdown()

        # 2. Test VisionClient completion against real loopback socket
        client = VisionClient(settings=settings)
        try:
            text, raw_json, latency = client.complete(
                image_b64="data:image/jpeg;base64,ZmFrZQ==",
                prompt="Text Recognition:",
            )
            assert text == "# Extracted OCR Heading\nReal loopback content."
            assert raw_json["id"] == "cmpl-test-loopback"
            assert latency > 0.0
        finally:
            client.close()
    finally:
        server.shutdown()
        server.server_close()


def test_real_win32_job_object_creation_and_assignment():
    """Verify real unmocked Win32 Job Object creation, process assignment, and handle cleanup on Windows."""
    if sys.platform != "win32":
        pytest.skip("Win32 Job Objects are Windows-only")

    from core.server_manager import _create_kill_on_close_job, _assign_process_to_job, _close_job_handle
    import subprocess

    job = _create_kill_on_close_job()
    assert job is not None and job != 0

    proc = subprocess.Popen(
        ["cmd.exe", "/c", "exit", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    handle = getattr(proc, "_handle", None)
    assert handle is not None
    assigned = _assign_process_to_job(job, int(handle))
    proc.wait(timeout=5)
    _close_job_handle(job)

    assert assigned is True


def test_server_manager_trust_env_disabled() -> None:
    """Verify ServerManager default session has trust_env=False to block proxy leaks."""
    mgr = ServerManager()
    try:
        assert mgr._session.trust_env is False
    finally:
        mgr.shutdown()




