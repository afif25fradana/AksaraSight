"""Unit tests for core/server_manager.py."""

from collections import deque
from pathlib import Path
import subprocess
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
    finally:
        mgr.shutdown()


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
