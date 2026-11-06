"""Tests for Linux diagnostics, settings resolution, and desktop integration (WP4)."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, List, Tuple
from unittest.mock import MagicMock
import pytest

from config.settings import Settings, _resolve_default_env_path
from core.diagnostics import DiagnosticStatus, run_diagnostics
from core.hardware import HardwareProfile
from core.server_manager import ServerStatus
from tests.web_fixtures import AsgiClient, _isolated_frozen_logging_state
from web.app import create_app, _pick_executable_file


# ---------------------------------------------------------------------------
# Section 1: Diagnostics (core/diagnostics.py)
# ---------------------------------------------------------------------------

def test_linux_diagnostics_hardware_detection_exception_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_diagnostics() must handle hardware probe exceptions gracefully without crashing."""
    monkeypatch.setattr(sys, "platform", "linux")

    def failing_detector() -> HardwareProfile:
        raise RuntimeError("Permission denied reading /sys/devices/virtual/dmi/id")

    try:
        report = run_diagnostics(
            hardware_detector=failing_detector,
            runtime_checker=lambda **kw: False,
            server_prober=lambda *a, **k: (ServerStatus.OFFLINE, "Server offline"),
        )
    except RuntimeError as exc:
        pytest.fail(f"run_diagnostics() crashed on hardware detector exception: {exc}")

    assert report is not None
    hw_checks = [c for c in report.checks if c.name in ("Hardware Detection", "Acceleration")]
    assert any(c.status in (DiagnosticStatus.WARN, DiagnosticStatus.FAIL) for c in hw_checks)
    assert "CPU" in report.format_text()


def test_linux_diagnostics_managed_cuda_fails_with_remediation(monkeypatch: pytest.MonkeyPatch) -> None:
    """CUDA managed runtime on Linux must trigger FAIL check with clear alternative advice."""
    monkeypatch.setattr(sys, "platform", "linux")

    settings = Settings(
        runtime_mode="managed",
        managed_backend_override="cuda",
    )
    fake_profile = HardwareProfile(
        cpu_name="x86_64 AMD EPYC",
        gpu_name="NVIDIA GeForce RTX 4090",
        cuda_available=True,
        cuda_supported=False,
        cuda_incompatibility_reason="CUDA managed runtime is not supported on Linux",
        recommended_backend="vulkan",
    )

    report = run_diagnostics(
        settings=settings,
        hardware_detector=lambda: fake_profile,
        runtime_checker=lambda **kw: False,
        server_prober=lambda *a, **k: (ServerStatus.OFFLINE, "Server offline"),
    )

    runtime_checks = [c for c in report.checks if "Runtime" in c.name or c.name == "Managed Runtime"]
    assert len(runtime_checks) >= 1
    assert any(c.status == DiagnosticStatus.FAIL for c in runtime_checks)

    remediation_text = " ".join(report.remediations)
    full_text = report.format_text()
    assert (
        "CUDA managed runtime is not supported on Linux" in remediation_text
        or "CUDA managed runtime is not supported on Linux" in full_text
    )
    assert any(kw in remediation_text.lower() for kw in ("vulkan", "cpu", "custom"))


def test_linux_diagnostics_expected_path_uses_platform_executable_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 3 runtime checks must reference 'llama-server' without '.exe' extension on Linux."""
    monkeypatch.setattr(sys, "platform", "linux")

    settings = Settings(
        runtime_mode="managed",
        managed_backend_override="vulkan",
    )

    report = run_diagnostics(
        settings=settings,
        runtime_checker=lambda **kw: False,
        server_prober=lambda *a, **k: (ServerStatus.OFFLINE, "Server offline"),
    )

    runtime_checks = [c for c in report.checks if "Runtime" in c.name and c.details]
    assert len(runtime_checks) >= 1
    for check in runtime_checks:
        details = str(check.details)
        assert not details.endswith(".exe"), f"Binary path unexpectedly ended with .exe: {details}"
        assert details.endswith("llama-server") or "llama-server" in details


def test_linux_diagnostics_custom_binary_not_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When custom binary on Linux exists but lacks execute permissions, diagnostics must emit FAIL with chmod +x remediation."""
    monkeypatch.setattr(sys, "platform", "linux")

    fake_bin = tmp_path / "custom-llama-server"
    fake_bin.write_text("#!/bin/sh\necho hi", encoding="utf-8")

    settings = Settings(
        runtime_mode="custom",
        llama_server_path=str(fake_bin),
    )

    real_access = os.access

    def fake_access(path: Any, mode: int, *args: Any, **kwargs: Any) -> bool:
        if mode == os.X_OK and Path(path).resolve() == fake_bin.resolve():
            return False
        return real_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "access", fake_access)

    report = run_diagnostics(
        settings=settings,
        runtime_checker=lambda **kw: False,
        server_prober=lambda *a, **k: (ServerStatus.OFFLINE, "Server offline"),
    )

    custom_checks = [c for c in report.checks if c.name == "Custom Binary"]
    assert len(custom_checks) == 1
    check = custom_checks[0]
    assert check.status == DiagnosticStatus.FAIL
    assert "NOT EXECUTABLE" in check.message.upper()

    remediations_str = " ".join(report.remediations)
    assert "chmod +x" in remediations_str
    assert f"[FAIL] Custom Binary:       {fake_bin} (NOT EXECUTABLE)" in report.format_text()


# ---------------------------------------------------------------------------
# Section 2: Desktop Integration (web/app.py)
# ---------------------------------------------------------------------------

def test_linux_launch_os_shell_file_reveals_parent_dir_and_returns_file_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Linux, revealing a file must pass its parent directory to xdg-open while returning file path."""
    import web.app as web_app

    monkeypatch.setattr(sys, "platform", "linux")

    out_dir = tmp_path / "output_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_file = out_dir / "report.md"
    sample_file.write_text("# Report", encoding="utf-8")

    run_calls: List[Tuple[Any, ...]] = []
    def fake_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        run_calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    # 1. Direct helper test: _launch_os_shell(target)
    assert hasattr(web_app, "_launch_os_shell"), "web.app must export _launch_os_shell(target)"
    opened, target = getattr(web_app, "_launch_os_shell")(sample_file)
    assert opened is True
    assert target == sample_file
    assert run_calls[-1][0][0] == ["xdg-open", str(sample_file.parent)]

    # 2. HTTP endpoint test: POST /api/output/open
    app = create_app(output_dir=out_dir)
    client = AsgiClient(app)
    status_code, _, body = client.post(
        "/api/output/open",
        headers={"content-type": "application/json"},
        body=json.dumps({"path": "report.md"}).encode("utf-8"),
    )
    assert status_code == 200
    payload = json.loads(body.decode("utf-8"))
    assert payload["opened"] is True
    assert payload["target"] == str(sample_file.resolve())
    assert run_calls[-1][0][0] == ["xdg-open", str(sample_file.parent)]


def test_linux_pick_executable_falls_back_to_kdialog_when_zenity_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_pick_executable_file() on Linux must attempt kdialog when zenity is unavailable."""
    monkeypatch.setattr(sys, "platform", "linux")

    dialog_cmds: List[List[str]] = []

    def mock_subprocess_run(cmd: List[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        dialog_cmds.append(cmd)
        if cmd[0] == "zenity":
            raise FileNotFoundError("No such file or directory: 'zenity'")
        if cmd[0] == "kdialog":
            return subprocess.CompletedProcess(
                cmd,
                returncode=0,
                stdout="/usr/local/bin/llama-server\n",
                stderr="",
            )
        raise ValueError(f"Unexpected dialog executable: {cmd[0]}")

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    chosen = _pick_executable_file()
    assert chosen == "/usr/local/bin/llama-server"
    assert len(dialog_cmds) == 2
    assert dialog_cmds[0][0] == "zenity"
    assert dialog_cmds[1] == ["kdialog", "--getopenfilename", ".", "--title", "Select llama-server Executable"]


def test_linux_pick_executable_returns_none_when_both_zenity_and_kdialog_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_pick_executable_file() must return None without crashing when no GUI dialog utility is found."""
    monkeypatch.setattr(sys, "platform", "linux")

    def mock_subprocess_missing(cmd: List[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        raise FileNotFoundError(f"Binary {cmd[0]} not found")

    monkeypatch.setattr(subprocess, "run", mock_subprocess_missing)

    chosen = _pick_executable_file()
    assert chosen is None


def test_windows_pick_executable_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """_pick_executable_file() on Windows invokes PowerShell OpenFileDialog."""
    monkeypatch.setattr(sys, "platform", "win32")

    # Success with path
    def mock_pwsh_success(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=0, stdout="C:\\bin\\llama-server.exe\n")

    monkeypatch.setattr(subprocess, "run", mock_pwsh_success)
    assert _pick_executable_file() == "C:\\bin\\llama-server.exe"

    # User cancelled (empty stdout)
    def mock_pwsh_cancel(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=0, stdout="   \n")

    monkeypatch.setattr(subprocess, "run", mock_pwsh_cancel)
    assert _pick_executable_file() is None

    # Non-zero returncode
    def mock_pwsh_fail(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=1, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_pwsh_fail)
    assert _pick_executable_file() is None

    # Exception / timeout
    def mock_pwsh_err(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=120)

    monkeypatch.setattr(subprocess, "run", mock_pwsh_err)
    assert _pick_executable_file() is None


def test_darwin_pick_executable_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """_pick_executable_file() on Darwin invokes osascript."""
    monkeypatch.setattr(sys, "platform", "darwin")

    # Success with path
    def mock_osa_success(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=0, stdout="/usr/local/bin/llama-server\n")

    monkeypatch.setattr(subprocess, "run", mock_osa_success)
    assert _pick_executable_file() == "/usr/local/bin/llama-server"

    # User cancelled (empty stdout)
    def mock_osa_cancel(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_osa_cancel)
    assert _pick_executable_file() is None

    # Non-zero returncode
    def mock_osa_fail(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args[0] if args else [], returncode=1, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_osa_fail)
    assert _pick_executable_file() is None

    # Exception / timeout
    def mock_osa_err(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=120)

    monkeypatch.setattr(subprocess, "run", mock_osa_err)
    assert _pick_executable_file() is None


def test_linux_pick_executable_dialog_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """_pick_executable_file() on Linux handles empty outputs, non-zero exits, and unexpected exceptions."""
    monkeypatch.setattr(sys, "platform", "linux")

    # 1. Zenity returns code 0 but empty string (cancelled)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="  \n"))
    assert _pick_executable_file() is None

    # 2. Zenity returns non-zero returncode
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=1, stdout=""))
    assert _pick_executable_file() is None

    # 3. Zenity raises unexpected Exception (not FileNotFoundError)
    def _zenity_err(*a, **k):
        raise RuntimeError("Zenity D-Bus protocol error")
    monkeypatch.setattr(subprocess, "run", _zenity_err)
    assert _pick_executable_file() is None

    # 4. Zenity missing, kdialog returns code 0 but empty string (cancelled)
    def _kdialog_cancel(cmd, *a, **k):
        if cmd[0] == "zenity":
            raise FileNotFoundError("no zenity")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=" \n")
    monkeypatch.setattr(subprocess, "run", _kdialog_cancel)
    assert _pick_executable_file() is None

    # 5. Zenity missing, kdialog returns non-zero returncode
    def _kdialog_fail(cmd, *a, **k):
        if cmd[0] == "zenity":
            raise FileNotFoundError("no zenity")
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="")
    monkeypatch.setattr(subprocess, "run", _kdialog_fail)
    assert _pick_executable_file() is None

    # 6. Zenity missing, kdialog raises unexpected Exception
    def _kdialog_err(cmd, *a, **k):
        if cmd[0] == "zenity":
            raise FileNotFoundError("no zenity")
        raise RuntimeError("KDE D-Bus error")
    monkeypatch.setattr(subprocess, "run", _kdialog_err)
    assert _pick_executable_file() is None


def test_launch_os_shell_cross_platform_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_launch_os_shell launches appropriate native file manager across Windows, macOS, and Linux."""
    import web.app as web_app
    launch_fn = getattr(web_app, "_launch_os_shell")

    test_file = tmp_path / "doc.pdf"
    test_file.write_bytes(b"%PDF")
    test_dir = tmp_path / "folder"
    test_dir.mkdir()

    calls: List[Any] = []
    def fake_run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    # 1. Windows: file reveals in explorer
    calls.clear()
    monkeypatch.setattr(sys, "platform", "win32")
    ok, ret = launch_fn(test_file)
    assert ok is True and ret == test_file
    assert any("explorer.exe /select," in str(c) for c in calls)

    # 2. Windows: directory opens via os.startfile
    startfile_calls: List[Path] = []
    monkeypatch.setattr(os, "startfile", lambda p: startfile_calls.append(p), raising=False)
    ok, ret = launch_fn(test_dir)
    assert ok is True and ret == test_dir
    assert startfile_calls == [test_dir]

    # 3. Darwin: file reveals via open -R
    calls.clear()
    monkeypatch.setattr(sys, "platform", "darwin")
    ok, ret = launch_fn(test_file)
    assert ok is True and ret == test_file
    assert calls[-1] == ["open", "-R", str(test_file)]

    # 4. Darwin: directory opens via open
    calls.clear()
    ok, ret = launch_fn(test_dir)
    assert ok is True and ret == test_dir
    assert calls[-1] == ["open", str(test_dir)]

    # 5. Linux: directory opens target itself via xdg-open
    calls.clear()
    monkeypatch.setattr(sys, "platform", "linux")
    ok, ret = launch_fn(test_dir)
    assert ok is True and ret == test_dir
    assert calls[-1] == ["xdg-open", str(test_dir)]


def test_linux_runtime_download_endpoints_use_get_exe_name(

    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime status and download endpoints must resolve platform-aware binary names via _get_exe_name()."""
    import web.app as web_app

    assert hasattr(web_app, "_get_exe_name"), "web.app must export _get_exe_name()"
    get_exe = getattr(web_app, "_get_exe_name")

    monkeypatch.setattr(sys, "platform", "linux")
    assert get_exe() == "llama-server"

    monkeypatch.setattr(sys, "platform", "win32")
    assert get_exe() == "llama-server.exe"

    monkeypatch.setattr(sys, "platform", "linux")
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    status_code, _, body = client.get("/api/runtime/status")
    assert status_code == 200
    data = json.loads(body.decode("utf-8"))
    expected_path = data.get("expected_path", "")
    assert not expected_path.endswith(".exe"), f"expected_path ended with .exe on Linux: {expected_path}"
    assert expected_path.endswith("llama-server")


# ---------------------------------------------------------------------------
# Section 3: Settings & Log Paths (config/settings.py, web/__main__.py)
# ---------------------------------------------------------------------------

def test_linux_frozen_env_path_read_only_fallback_xdg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When frozen executable is in a read-only directory on Linux, .env falls back to XDG_CONFIG_HOME."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("AKSARA_ENV_FILE", raising=False)

    fake_dir = tmp_path / "read_only_bin"
    fake_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = fake_dir / "aksarasight"
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    custom_xdg = tmp_path / "xdg_config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom_xdg))

    real_access = os.access
    def fake_access(path: Any, mode: int, *args: Any, **kwargs: Any) -> bool:
        if mode == os.W_OK and Path(path).resolve() == fake_dir.resolve():
            return False
        return real_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "access", fake_access)

    resolved = _resolve_default_env_path()
    assert resolved == custom_xdg / "aksarasight" / "settings.env"


def test_linux_frozen_env_path_read_only_fallback_home_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When XDG_CONFIG_HOME is unset and executable dir is read-only, .env defaults to ~/.config."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("AKSARA_ENV_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    fake_home = tmp_path / "mock_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    fake_dir = tmp_path / "read_only_bin"
    fake_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = fake_dir / "aksarasight"
    monkeypatch.setattr(sys, "executable", str(fake_exe))

    real_access = os.access
    def fake_access(path: Any, mode: int, *args: Any, **kwargs: Any) -> bool:
        if mode == os.W_OK and Path(path).resolve() == fake_dir.resolve():
            return False
        return real_access(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "access", fake_access)

    resolved = _resolve_default_env_path()
    assert resolved == fake_home / ".config" / "aksarasight" / "settings.env"


def test_linux_frozen_env_path_writable_uses_exe_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When frozen executable directory is writable on Linux, .env lives adjacent to binary."""
    writable_dir = tmp_path / "portable_app"
    writable_dir.mkdir(parents=True, exist_ok=True)
    portable_exe = writable_dir / "aksarasight"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("AKSARA_ENV_FILE", raising=False)
    monkeypatch.setattr(sys, "executable", str(portable_exe))
    monkeypatch.setattr(os, "access", lambda path, mode, *a, **k: True)

    resolved = _resolve_default_env_path()
    assert resolved == writable_dir / ".env"


def test_linux_frozen_logging_xdg_state_home_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Linux with LOCALAPPDATA unset, frozen logging must target $XDG_STATE_HOME/aksarasight/logs/app.log."""
    from web.__main__ import _setup_frozen_logging

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    xdg_state = tmp_path / "xdg_state"
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))

    with _isolated_frozen_logging_state():
        log_file = _setup_frozen_logging()
        assert log_file is not None
        assert log_file == xdg_state / "aksarasight" / "logs" / "app.log"
        assert log_file.exists()


def test_linux_frozen_logging_xdg_state_home_default_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Linux with XDG_STATE_HOME unset, frozen logging defaults to ~/.local/state/aksarasight/logs/app.log."""
    from web.__main__ import _setup_frozen_logging

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    fake_home = tmp_path / "mock_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    with _isolated_frozen_logging_state():
        log_file = _setup_frozen_logging()
        assert log_file is not None
        assert log_file == fake_home / ".local" / "state" / "aksarasight" / "logs" / "app.log"
        assert log_file.exists()


def test_linux_headless_browser_auto_open_suppression(monkeypatch: pytest.MonkeyPatch) -> None:
    """On headless Linux (no display, non-WSL), browser auto-open must be suppressed."""
    import web.__main__ as web_main

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)

    if hasattr(web_main, "_probe_wsl"):
        monkeypatch.setattr(web_main, "_probe_wsl", lambda: False)

    timers: List[threading.Timer] = []
    real_timer = threading.Timer

    def spy_timer(interval: float, func: Any) -> threading.Timer:
        t = real_timer(0.01, func)
        timers.append(t)
        return t

    monkeypatch.setattr(threading, "Timer", spy_timer)
    monkeypatch.setattr(web_main, "is_port_in_use", lambda host, port: False)
    monkeypatch.setattr(web_main, "create_app", lambda **k: "mock_app")
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["web", "--port", "8128"])

    with _isolated_frozen_logging_state():
        web_main.main()

    assert len(timers) == 0, "Browser auto-open timer must not be scheduled on headless Linux"


def test_linux_browser_auto_open_allowed_on_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    """On WSL Linux, browser auto-open must remain active even without Linux X11 display."""
    import web.__main__ as web_main

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    if hasattr(web_main, "_probe_wsl"):
        monkeypatch.setattr(web_main, "_probe_wsl", lambda: True)
    else:
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-22.04")

    timers: List[threading.Timer] = []
    real_timer = threading.Timer

    def spy_timer(interval: float, func: Any) -> threading.Timer:
        t = real_timer(0.01, func)
        timers.append(t)
        return t

    monkeypatch.setattr(threading, "Timer", spy_timer)
    monkeypatch.setattr(web_main, "is_port_in_use", lambda host, port: False)
    monkeypatch.setattr(web_main, "create_app", lambda **k: "mock_app")
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["web", "--port", "8129"])

    with _isolated_frozen_logging_state():
        web_main.main()

    assert len(timers) == 1, "Browser auto-open must be scheduled on WSL"


def test_linux_browser_auto_open_allowed_on_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """On desktop Linux with DISPLAY set, browser auto-open must remain active."""
    import web.__main__ as web_main

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0.0")

    if hasattr(web_main, "_probe_wsl"):
        monkeypatch.setattr(web_main, "_probe_wsl", lambda: False)

    timers: List[threading.Timer] = []
    real_timer = threading.Timer

    def spy_timer(interval: float, func: Any) -> threading.Timer:
        t = real_timer(0.01, func)
        timers.append(t)
        return t

    monkeypatch.setattr(threading, "Timer", spy_timer)
    monkeypatch.setattr(web_main, "is_port_in_use", lambda host, port: False)
    monkeypatch.setattr(web_main, "create_app", lambda **k: "mock_app")
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["web", "--port", "8130"])

    with _isolated_frozen_logging_state():
        web_main.main()

    assert len(timers) == 1, "Browser auto-open must be scheduled when DISPLAY is present"


def test_linux_probe_wsl_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_probe_wsl() must accurately detect WSL environment via env or /proc/version."""
    import web.__main__ as web_main

    assert hasattr(web_main, "_probe_wsl"), "web.__main__ must export _probe_wsl()"
    probe_wsl = getattr(web_main, "_probe_wsl")

    # Non-Linux platform always returns False
    monkeypatch.setattr(sys, "platform", "win32")
    assert probe_wsl() is False

    monkeypatch.setattr(sys, "platform", "linux")

    # WSL via environment variable
    monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
    assert probe_wsl() is True

    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)

    # WSL via /proc/version kernel string
    fake_proc = tmp_path / "fake_proc_version"
    fake_proc.write_text("Linux version 6.6.137.1-microsoft-standard-WSL2 (gcc) #1 SMP")
    real_read_text = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *a, **k: fake_proc.read_text() if getattr(self, "as_posix", lambda: str(self))() == "/proc/version" else real_read_text(self, *a, **k),
    )
    assert probe_wsl() is True


def test_linux_settings_save_to_env_creates_parent_and_enforces_0o600(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings.save_to_env() must create nonexistent parent directories and enforce 0o600 on POSIX."""
    nested_dir = tmp_path / "nonexistent_sub" / "aksarasight"
    target_env = nested_dir / "settings.env"
    assert not nested_dir.exists()

    orig_env = dict(os.environ)
    try:
        settings = Settings(runtime_mode="custom", llama_server_path="/custom/llama-server")
        saved_path = settings.save_to_env(target_env)

        assert saved_path == target_env
        assert target_env.is_file()
        assert "OCR_RUNTIME_MODE='custom'" in target_env.read_text(encoding="utf-8")

        if os.name == "posix":
            mode = target_env.stat().st_mode & 0o777
            assert mode == 0o600
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


def test_linux_open_browser_wsl_wslview(monkeypatch: pytest.MonkeyPatch) -> None:
    """_open_browser() on headless WSL uses wslview when present."""
    import shutil
    import web.__main__ as web_main

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(web_main, "_probe_wsl", lambda: True)

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/wslview" if cmd == "wslview" else None)

    runs: List[List[str]] = []
    def fake_run(cmd: List[str], check: bool = False) -> None:
        runs.append(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    web_main._open_browser("http://127.0.0.1:8000")
    assert len(runs) == 1
    assert runs[0] == ["wslview", "http://127.0.0.1:8000"]


def test_linux_open_browser_wsl_powershell_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """_open_browser() on headless WSL falls back to powershell.exe when wslview is missing."""
    import shutil
    import web.__main__ as web_main

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(web_main, "_probe_wsl", lambda: True)

    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/mnt/c/Windows/System32/powershell.exe" if cmd == "powershell.exe" else None,
    )

    runs: List[List[str]] = []
    def fake_run(cmd: List[str], check: bool = False) -> None:
        runs.append(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    web_main._open_browser("http://127.0.0.1:8000")
    assert len(runs) == 1
    assert runs[0] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Start-Process 'http://127.0.0.1:8000'",
    ]


def test_linux_open_browser_standard_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """_open_browser() falls back to webbrowser.open when display is present or not WSL."""
    import web.__main__ as web_main
    import webbrowser

    opened: List[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))

    # Case 1: win32
    monkeypatch.setattr(sys, "platform", "win32")
    web_main._open_browser("http://127.0.0.1:8000")
    assert opened == ["http://127.0.0.1:8000"]

    # Case 2: Linux with DISPLAY
    opened.clear()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    web_main._open_browser("http://127.0.0.1:8000")
    assert opened == ["http://127.0.0.1:8000"]


def test_frozen_logging_windows_fallback_when_localappdata_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows with LOCALAPPDATA unset, frozen logging defaults to ~/AppData/Local/AksaraSight/logs/app.log."""
    from web.__main__ import _setup_frozen_logging

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    fake_home = tmp_path / "mock_win_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    with _isolated_frozen_logging_state():
        log_file = _setup_frozen_logging()
        assert log_file is not None
        assert log_file == fake_home / "AppData" / "Local" / "AksaraSight" / "logs" / "app.log"
        assert log_file.exists()


def test_linux_diagnostics_host_shared_libraries_pass_and_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_diagnostics() verifies libgomp.so.1 and libvulkan.so.1 on Linux using ctypes."""
    import ctypes

    monkeypatch.setattr(sys, "platform", "linux")

    settings = Settings(runtime_mode="managed", managed_backend_override="vulkan")
    fake_profile = HardwareProfile(recommended_backend="vulkan")

    # Case 1: Both libraries present
    def fake_cdll_success(name: str) -> Any:
        return MagicMock()

    monkeypatch.setattr(ctypes, "CDLL", fake_cdll_success)
    report_pass = run_diagnostics(
        settings=settings,
        hardware_detector=lambda: fake_profile,
        runtime_checker=lambda **kw: True,
        runtime_path_getter=lambda **kw: Path("/usr/bin/llama-server"),
        server_prober=lambda *a, **k: (ServerStatus.READY, "Server ready"),
    )
    lib_checks_pass = [c for c in report_pass.checks if "Host Library" in c.name]
    assert len(lib_checks_pass) == 2
    assert all(c.status == DiagnosticStatus.PASS for c in lib_checks_pass)

    # Case 2: Both libraries missing -> emit FAIL with actionable package manager remediation
    def fake_cdll_fail(name: str) -> Any:
        raise OSError(f"{name}: cannot open shared object file")

    monkeypatch.setattr(ctypes, "CDLL", fake_cdll_fail)
    report_fail = run_diagnostics(
        settings=settings,
        hardware_detector=lambda: fake_profile,
        runtime_checker=lambda **kw: True,
        runtime_path_getter=lambda **kw: Path("/usr/bin/llama-server"),
        server_prober=lambda *a, **k: (ServerStatus.READY, "Server ready"),
    )
    lib_checks_fail = [c for c in report_fail.checks if "Host Library" in c.name]
    assert len(lib_checks_fail) == 2
    assert all(c.status == DiagnosticStatus.FAIL for c in lib_checks_fail)
    remediation_str = " ".join(report_fail.remediations)
    assert "sudo apt install libgomp1" in remediation_str
    assert "sudo apt install libvulkan1" in remediation_str
