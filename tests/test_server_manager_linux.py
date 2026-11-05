"""Linux-specific unit and integration tests for ServerManager process lifecycle and process group containment."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from core.hardware import HardwareProfile
from core.server_manager import ServerManager, ServerOwnership, ServerStatus


def test_server_manager_start_linux_uses_start_new_session_and_ld_library_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux ServerManager.start() spawns subprocess with start_new_session=True and prepended LD_LIBRARY_PATH."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/existing/lib64")

    fake_bin = tmp_path / "llama-server"
    fake_bin.write_text("binary", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_bin),
        runtime_mode="custom",
        model_repo="test-org/model-gguf",
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter(["[server] listening on 127.0.0.1:8080\n"])
    mock_proc.communicate.return_value = ("", "")

    try:
        with (
            patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")),
            patch("core.server_manager.get_cached_hardware_profile", return_value=HardwareProfile(recommended_backend="cpu")),
            patch("core.server_manager.subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            mgr.start()
            assert mock_popen.called
            _, popen_kwargs = mock_popen.call_args

            # Linux process group containment requires session leadership
            assert popen_kwargs.get("start_new_session") is True

            # Linux dynamic linker requires runtime directory in LD_LIBRARY_PATH
            env = popen_kwargs.get("env", {})
            assert "LD_LIBRARY_PATH" in env
            assert env["LD_LIBRARY_PATH"].startswith(f"{fake_bin.parent}:")
            assert "/existing/lib64" in env["LD_LIBRARY_PATH"]

            # Windows-only CREATE_NO_WINDOW flag must not be passed on Linux
            assert popen_kwargs.get("creationflags", 0) == 0
    finally:
        mgr.shutdown()


def test_server_manager_stop_linux_terminates_process_group_sigterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux ServerManager.stop() terminates the process group via os.killpg with SIGTERM."""
    monkeypatch.setattr("sys.platform", "linux")
    mock_killpg = MagicMock()
    monkeypatch.setattr(os, "killpg", mock_killpg, raising=False)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)

    mgr = ServerManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    mock_proc.stdout = None

    mgr._process = mock_proc
    mgr._ownership = ServerOwnership.MANAGED
    mgr._status = ServerStatus.READY

    mgr.stop()

    mock_killpg.assert_called_once_with(12345, signal.SIGTERM)
    assert mgr.status == ServerStatus.OFFLINE
    assert mgr.ownership == ServerOwnership.NONE
    assert mgr.is_managed is False


def test_server_manager_stop_linux_escalates_to_sigkill_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux ServerManager.stop() escalates to SIGKILL if SIGTERM times out after 3.0s."""
    monkeypatch.setattr("sys.platform", "linux")
    sigkill = getattr(signal, "SIGKILL", 9)
    if not hasattr(signal, "SIGKILL"):
        monkeypatch.setattr(signal, "SIGKILL", sigkill, raising=False)

    mock_killpg = MagicMock()
    monkeypatch.setattr(os, "killpg", mock_killpg, raising=False)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)

    mgr = ServerManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    mock_proc.stdout = None
    mock_proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="llama-server", timeout=3.0),
        0,
    ]

    mgr._process = mock_proc
    mgr._ownership = ServerOwnership.MANAGED
    mgr._status = ServerStatus.READY

    mgr.stop()

    assert mock_killpg.call_count == 2
    mock_killpg.assert_any_call(12345, signal.SIGTERM)
    mock_killpg.assert_any_call(12345, sigkill)
    assert mgr.status == ServerStatus.OFFLINE
    assert mgr.ownership == ServerOwnership.NONE


def test_server_manager_stop_linux_handles_process_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux ServerManager.stop() swallows ProcessLookupError gracefully when process already exited."""
    monkeypatch.setattr("sys.platform", "linux")
    mock_killpg = MagicMock(side_effect=ProcessLookupError("No such process"))
    monkeypatch.setattr(os, "killpg", mock_killpg, raising=False)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)

    mgr = ServerManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    mock_proc.stdout = None

    mgr._process = mock_proc
    mgr._ownership = ServerOwnership.MANAGED
    mgr._status = ServerStatus.READY

    mgr.stop()

    mock_killpg.assert_called_once_with(12345, signal.SIGTERM)
    assert mgr.status == ServerStatus.OFFLINE
    assert mgr.ownership == ServerOwnership.NONE
    assert mgr.is_managed is False


def test_server_manager_binary_not_found_message_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Binary not found error messages on Linux refer to 'llama-server' rather than 'llama-server.exe'."""
    monkeypatch.setattr("sys.platform", "linux")

    settings_missing_path = Settings(
        llama_server_path="/nonexistent/bin/llama-server",
        runtime_mode="custom",
        model_repo="test-org/model",
    )
    mgr1 = ServerManager(settings=settings_missing_path)

    with (
        patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")),
        pytest.raises(FileNotFoundError) as exc_info1,
    ):
        mgr1.start()

    err_msg1 = str(exc_info1.value)
    assert "llama-server" in err_msg1
    assert "llama-server.exe" not in err_msg1

    settings_empty = Settings(
        llama_server_path="",
        runtime_mode="custom",
        model_repo="test-org/model",
    )
    mgr2 = ServerManager(settings=settings_empty)

    with (
        patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")),
        patch("shutil.which", return_value=None),
        pytest.raises(FileNotFoundError) as exc_info2,
    ):
        mgr2.start()

    err_msg2 = str(exc_info2.value)
    assert "llama-server" in err_msg2
    assert "llama-server.exe" not in err_msg2


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups only")
def test_server_manager_linux_process_group_tree_termination_integration() -> None:
    """Real POSIX process group tree termination verifies grandchild cleanup."""
    child_code = (
        "import subprocess, sys, time\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(grandchild.pid, flush=True)\n"
        "time.sleep(60)\n"
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", child_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    child_pid = proc.pid
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()
    grandchild_pid = int(line)

    # Both child and grandchild must be active prior to termination
    os.kill(child_pid, 0)
    os.kill(grandchild_pid, 0)

    mgr = ServerManager()
    mgr._process = proc
    mgr._ownership = ServerOwnership.MANAGED
    mgr._status = ServerStatus.READY

    child_dead = False
    grandchild_dead = False
    try:
        mgr.stop()

        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                os.kill(child_pid, 0)
                child_dead = False
            except (ProcessLookupError, PermissionError):
                child_dead = True

            try:
                os.kill(grandchild_pid, 0)
                grandchild_dead = False
            except (ProcessLookupError, PermissionError):
                grandchild_dead = True

            if child_dead and grandchild_dead:
                break
            time.sleep(0.1)

        assert child_dead, f"Child process {child_pid} survived ServerManager.stop()"
        assert grandchild_dead, f"Grandchild process {grandchild_pid} survived ServerManager.stop()"
    finally:
        for pid in (grandchild_pid, child_pid):
            try:
                os.kill(pid, getattr(signal, "SIGKILL", 9))
            except (ProcessLookupError, PermissionError):
                pass


def test_server_manager_start_failure_after_popen_kills_process_group_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Linux, failure after Popen kills the process group with SIGKILL."""
    monkeypatch.setattr("sys.platform", "linux")
    mock_killpg = MagicMock()
    monkeypatch.setattr(os, "killpg", mock_killpg, raising=False)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)

    fake_bin = tmp_path / "llama-server"
    fake_bin.write_text("binary", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_bin),
        runtime_mode="custom",
        model_repo="test-org/model",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.poll.return_value = None
    mock_stdout = MagicMock()
    mock_proc.stdout = mock_stdout

    sigkill = getattr(signal, "SIGKILL", 9)
    if not hasattr(signal, "SIGKILL"):
        monkeypatch.setattr(signal, "SIGKILL", sigkill, raising=False)

    with (
        patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")),
        patch("core.server_manager.subprocess.Popen", return_value=mock_proc),
        patch("threading.Thread.start", side_effect=RuntimeError("Can't start thread")),
        pytest.raises(RuntimeError, match="Failed to launch llama-server"),
    ):
        mgr.start()

    mock_killpg.assert_called_once_with(9999, sigkill)
    mock_proc.wait.assert_called_once_with(timeout=2.0)
    mock_stdout.close.assert_called_once()


def test_server_manager_stop_linux_sigkill_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux stop() handles ProcessLookupError on SIGKILL escalation gracefully."""
    monkeypatch.setattr("sys.platform", "linux")
    sigkill = getattr(signal, "SIGKILL", 9)
    if not hasattr(signal, "SIGKILL"):
        monkeypatch.setattr(signal, "SIGKILL", sigkill, raising=False)

    def _fake_killpg(pgid, sig):
        if sig == sigkill:
            raise ProcessLookupError("Already exited")

    mock_killpg = MagicMock(side_effect=_fake_killpg)
    monkeypatch.setattr(os, "killpg", mock_killpg, raising=False)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)

    mgr = ServerManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    mock_proc.stdout = None
    mock_proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="llama-server", timeout=3.0),
        0,
    ]

    mgr._process = mock_proc
    mgr._ownership = ServerOwnership.MANAGED
    mgr._status = ServerStatus.READY

    mgr.stop()

    assert mock_killpg.call_count == 2
    assert mgr.status == ServerStatus.OFFLINE


def test_server_manager_stop_linux_getpgid_error_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Linux stop() falls back to proc.pid if os.getpgid fails."""
    monkeypatch.setattr("sys.platform", "linux")
    mock_killpg = MagicMock()
    monkeypatch.setattr(os, "killpg", mock_killpg, raising=False)
    monkeypatch.setattr(os, "getpgid", MagicMock(side_effect=ProcessLookupError), raising=False)

    mgr = ServerManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.poll.return_value = None
    mock_proc.stdout = None

    mgr._process = mock_proc
    mgr._ownership = ServerOwnership.MANAGED
    mgr._status = ServerStatus.READY

    mgr.stop()

    mock_killpg.assert_called_once_with(12345, signal.SIGTERM)
