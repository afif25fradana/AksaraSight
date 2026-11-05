"""Tests for Web lifespan, CLI entrypoint, port conflict, and logging isolation."""

import asyncio
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from core.server_manager import ServerStatus
from web.app import create_app
from web.orchestrator import JobState
from tests.web_fixtures import (
    _isolated_frozen_logging_state,
)


@pytest.fixture(autouse=True)
def _isolate_entrypoint_web_env():
    """Isolate and restore AKSARA_WEB_* process env vars modified by main()."""
    old_dev = os.environ.get("AKSARA_WEB_DEV_MODE")
    old_port = os.environ.get("AKSARA_WEB_PORT")
    try:
        yield
    finally:
        for var, old in [("AKSARA_WEB_DEV_MODE", old_dev), ("AKSARA_WEB_PORT", old_port)]:
            if old is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old


def test_startup_sweep_cleans_up_stale_uploads(tmp_path: Path) -> None:
    """Verify startup sweep unlinks stale upload files left from previous sessions."""
    stale1 = tmp_path / "stale1.png"
    stale2 = tmp_path / "stale2.pdf"
    stale1.write_bytes(b"stale-data-1")
    stale2.write_bytes(b"stale-data-2")
    assert stale1.exists()
    assert stale2.exists()

    app = create_app(upload_dir=tmp_path)

    async def _run():
        async with app.router.lifespan_context(app):
            # After startup sweep, stale files should be unlinked immediately
            assert not stale1.exists()
            assert not stale2.exists()

    asyncio.run(_run())
    assert [p.name for p in tmp_path.iterdir() if p.name != ".instance.lock"] == []
    assert (tmp_path / ".instance.lock").exists()

def test_lifespan_cleans_up_upload_scratch(tmp_path: Path) -> None:
    """Verify FastAPI lifespan shutdown cleans up tracked files in upload directory."""
    app = create_app(upload_dir=tmp_path)

    async def _run_lifespan():
        async with app.router.lifespan_context(app):
            # Populate upload directory with session files during active lifecycle
            file1 = tmp_path / "session_file1.png"
            file2 = tmp_path / "session_file2.pdf"
            file1.write_bytes(b"data1")
            file2.write_bytes(b"data2")
            assert file1.exists()
            assert file2.exists()
            app.state.orchestrator.register_job(
                JobState(job_id="file1", filename="session_file1.png", file_path=file1, page_count=1)
            )
            app.state.orchestrator.register_job(
                JobState(job_id="file2", filename="session_file2.pdf", file_path=file2, page_count=1)
            )

    asyncio.run(_run_lifespan())

    # On shutdown, tracked files in upload directory must be deleted, retaining advisory .instance.lock
    assert [p.name for p in tmp_path.iterdir() if p.name != ".instance.lock"] == []
    assert (tmp_path / ".instance.lock").exists()

def test_concurrent_instance_skips_startup_sweep(tmp_path: Path) -> None:
    """Verify concurrent app instance skips startup sweep when another holds .instance.lock."""
    from web.app import _acquire_instance_lock, _release_instance_lock

    active_file = tmp_path / "active_session_file.png"
    active_file.write_bytes(b"active-content")

    # Primary instance acquires lock
    lock1 = _acquire_instance_lock(tmp_path)
    try:
        app2 = create_app(upload_dir=tmp_path)

        async def _run_second():
            async with app2.router.lifespan_context(app2):
                assert app2.state.instance_lock is None
                assert active_file.exists()
                assert active_file.read_bytes() == b"active-content"

        asyncio.run(_run_second())
        assert active_file.exists()
    finally:
        _release_instance_lock(lock1)
        lock_path = tmp_path / ".instance.lock"
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass

def test_is_port_in_use() -> None:
    """Verify is_port_in_use correctly detects open vs available ports."""
    import socket
    from web.__main__ import is_port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        assert is_port_in_use("127.0.0.1", port) is True

    assert is_port_in_use("127.0.0.1", port) is False

def test_lifespan_shutdown_unlinks_only_own_jobs(tmp_path: Path) -> None:
    """Verify lifespan shutdown unlinks only jobs registered to this instance."""
    app = create_app(upload_dir=tmp_path)
    orch = app.state.orchestrator

    foreign_file = tmp_path / "foreign.pdf"
    own_file = tmp_path / "own.pdf"

    async def _run():
        async with app.router.lifespan_context(app):
            foreign_file.write_bytes(b"%PDF-1.4 foreign mock content")
            own_file.write_bytes(b"%PDF-1.4 own mock content")
            own_job = JobState(
                job_id="own_job_id",
                filename="own.pdf",
                file_path=own_file,
                page_count=1,
            )
            orch.register_job(own_job)
            assert foreign_file.exists()
            assert own_file.exists()

    asyncio.run(_run())

    assert not own_file.exists()
    assert foreign_file.exists()

def test_create_app_resolves_meipass_static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify create_app resolves static directory from sys._MEIPASS when frozen."""
    meipass_dir = tmp_path / "bundle"
    static_dir = meipass_dir / "web" / "static"
    static_dir.mkdir(parents=True)
    index_file = static_dir / "index.html"
    index_file.write_text("<!doctype html><html><body>MEIPASS Bundle</body></html>", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(upload_dir=upload_dir)
    try:
        static_routes = [r for r in app.routes if getattr(r, "name", None) == "static"]
        assert len(static_routes) == 1
        mounted_dir = getattr(static_routes[0].app, "directory", None)
        assert mounted_dir is not None
        assert Path(mounted_dir).resolve() == static_dir.resolve()
        assert (Path(mounted_dir) / "index.html").is_file()
        assert "MEIPASS Bundle" in (Path(mounted_dir) / "index.html").read_text(encoding="utf-8")
    finally:
        if hasattr(app.state, "orchestrator") and app.state.orchestrator:
            app.state.orchestrator.shutdown()

def test_build_parser_no_browser_flag() -> None:
    """Verify build_parser supports and correctly parses --no-browser flag."""
    from web.__main__ import build_parser

    parser = build_parser()
    args_true = parser.parse_args(["--no-browser"])
    assert args_true.no_browser is True

    args_default = parser.parse_args([])
    assert args_default.no_browser is False

def test_setup_frozen_logging_idempotency_and_oserror_resilience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify _setup_frozen_logging is idempotent and resilient to OSError."""
    import logging
    from web.__main__ import _setup_frozen_logging

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    original_excepthook = sys.excepthook

    try:
        log_path_1 = _setup_frozen_logging()
        assert log_path_1 is not None
        assert log_path_1.is_file()

        file_handlers_before = [
            h for h in root_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers_before) >= 1

        log_path_2 = _setup_frozen_logging()
        assert log_path_2 == log_path_1
        file_handlers_after = [
            h for h in root_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers_after) == len(file_handlers_before)

        with patch("pathlib.Path.mkdir", side_effect=OSError("Disk full or read-only")):
            res = _setup_frozen_logging()
            assert res is None
    finally:
        for h in list(root_logger.handlers):
            if h not in original_handlers:
                try:
                    h.close()
                except Exception:
                    pass
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
        sys.excepthook = original_excepthook


def test_frozen_logging_web_and_core_debug_levels(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify _setup_frozen_logging configures web and core loggers at DEBUG and root at INFO."""
    import logging
    import uuid
    from web.__main__ import _setup_frozen_logging

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    web_logger = logging.getLogger("web")
    core_logger = logging.getLogger("core")
    orig_web_level = web_logger.level
    orig_core_level = core_logger.level

    with _isolated_frozen_logging_state():
        try:
            log_path = _setup_frozen_logging()
            assert log_path is not None
            assert logging.getLogger().level == logging.INFO
            assert web_logger.level == logging.DEBUG
            assert core_logger.level == logging.DEBUG

            file_handlers = [
                h for h in logging.getLogger().handlers
                if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(log_path.resolve())
            ]
            assert len(file_handlers) >= 1
            fh = file_handlers[0]
            assert fh.level == logging.DEBUG

            test_msg = f"TEST_DEBUG_PROBE_{uuid.uuid4().hex[:8]}"
            web_logger.debug(test_msg)
            fh.flush()

            log_content = log_path.read_text(encoding="utf-8")
            assert test_msg in log_content
        finally:
            web_logger.setLevel(orig_web_level)
            core_logger.setLevel(orig_core_level)

def test_web_entrypoint_is_port_in_use_and_parser():
    """Verify is_port_in_use and build_parser in web.__main__."""
    import socket
    from web.__main__ import is_port_in_use, build_parser
    parser = build_parser()
    args = parser.parse_args(["--port", "9999", "--dev", "--reload", "--no-browser"])
    assert args.port == 9999
    assert args.dev is True
    assert args.reload is True
    assert args.no_browser is True

    # Free port check
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    assert is_port_in_use("127.0.0.1", free_port) is False

    # Occupied port check
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy_port = s.getsockname()[1]
        assert is_port_in_use("127.0.0.1", busy_port) is True

def test_web_entrypoint_main_host_rejection(monkeypatch):
    """Verify main() rejects non-loopback host binding with exit code 1."""
    import web.__main__ as web_main
    monkeypatch.setattr(sys, "argv", ["web", "--host", "192.168.1.50"])
    with pytest.raises(SystemExit) as exc_info:
        web_main.main()
    assert exc_info.value.code == 1

def test_web_entrypoint_main_port_in_use(monkeypatch):
    """Verify main() rejects startup if port is already bound."""
    import web.__main__ as web_main
    monkeypatch.setattr(sys, "argv", ["web", "--port", "8000"])
    monkeypatch.setattr(web_main, "is_port_in_use", lambda host, port: True)
    with pytest.raises(SystemExit) as exc_info:
        web_main.main()
    assert exc_info.value.code == 1

def test_web_entrypoint_main_dev_and_reload(monkeypatch):
    """Verify main() handles --dev and --reload flags."""
    import web.__main__ as web_main
    run_calls = []
    monkeypatch.delenv("AKSARA_WEB_DEV_MODE", raising=False)
    monkeypatch.delenv("AKSARA_WEB_PORT", raising=False)
    monkeypatch.setattr(sys, "argv", ["web", "--port", "8123", "--dev", "--reload"])
    monkeypatch.setattr(web_main, "is_port_in_use", lambda host, port: False)
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *a, **k: run_calls.append((a, k)))

    web_main.main()

    assert os.environ.get("AKSARA_WEB_DEV_MODE") == "1"
    assert os.environ.get("AKSARA_WEB_PORT") == "8123"
    assert len(run_calls) == 1
    assert run_calls[0][0] == ("web.app:create_app",)
    assert run_calls[0][1]["reload"] is True

def test_web_entrypoint_main_default_and_frozen(monkeypatch, tmp_path):
    """Verify main() handles standard execution and frozen browser timer."""
    import threading
    import web.__main__ as web_main
    run_calls = []
    monkeypatch.setattr(sys, "argv", ["web", "--port", "8124"])
    monkeypatch.setattr(web_main, "is_port_in_use", lambda host, port: False)
    monkeypatch.setattr(web_main, "create_app", lambda **k: "mock_app")
    monkeypatch.setattr(web_main.uvicorn, "run", lambda *a, **k: run_calls.append((a, k)))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("DISPLAY", ":0")

    # Spy on threading.Timer to verify browser spawn was scheduled
    timer_created = []
    real_timer = threading.Timer
    def mock_timer(interval, func):
        t = real_timer(0.01, func)
        timer_created.append(interval)
        return t
    monkeypatch.setattr(threading, "Timer", mock_timer)
    monkeypatch.setattr(web_main.webbrowser, "open", lambda url: None)

    with _isolated_frozen_logging_state():
        web_main.main()

    assert len(run_calls) == 1
    assert run_calls[0][0] == ("mock_app",)
    assert run_calls[0][1]["port"] == 8124
    assert len(timer_created) == 1
    assert timer_created[0] == 0.8

def test_web_entrypoint_setup_frozen_logging(monkeypatch, tmp_path):
    """Verify _setup_frozen_logging creates log file and installs excepthook."""
    import web.__main__ as web_main
    # Not frozen -> returns None
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert web_main._setup_frozen_logging() is None

    # Frozen
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    with _isolated_frozen_logging_state():
        log_file = web_main._setup_frozen_logging()
        assert log_file is not None
        assert log_file.name == "app.log"
        assert log_file.exists()

        # Test excepthook handles regular exception
        hook = sys.excepthook
        hook(ValueError, ValueError("test error"), None)

        # Test KeyboardInterrupt is forwarded to default excepthook
        forwarded = []
        monkeypatch.setattr(sys, "__excepthook__", lambda *a: forwarded.append(a))
        hook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert len(forwarded) == 1

def test_format_file_size_helper():
    """Verify _format_file_size renders B, KB, and MB accurately."""
    from web.app import _format_file_size
    assert _format_file_size(500) == "500 B"
    assert _format_file_size(2048) == "2.0 KB"
    assert _format_file_size(5 * 1024 * 1024) == "5.0 MB"

def test_instance_lock_helpers(tmp_path):
    """Verify _acquire_instance_lock and _release_instance_lock edge cases."""
    from web.app import _acquire_instance_lock, _release_instance_lock
    lock1 = _acquire_instance_lock(tmp_path)
    assert lock1 is not None

    # Acquiring again in same or competing process raises error
    if sys.platform == "win32":
        with pytest.raises(OSError):
            _acquire_instance_lock(tmp_path)

    _release_instance_lock(lock1)
    _release_instance_lock(None)  # No-op check

def test_app_lifespan_auto_start_managed_server(tmp_path):
    """Verify lifespan auto-starts managed server when auto_start_server=True and server is offline."""
    import asyncio
    from core.server_manager import ServerOwnership
    settings = Settings(auto_start_server=True)
    server_mgr = MagicMock()
    server_mgr.ownership = ServerOwnership.MANAGED

    async def _run():
        with patch("web.app.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            app = create_app(settings=settings, server_manager=server_mgr, upload_dir=tmp_path)
            async with app.router.lifespan_context(app):
                assert getattr(app.state, "server_managed", False) is True
            server_mgr.start.assert_called_once()
            server_mgr.shutdown.assert_called_once()

    asyncio.run(_run())

def test_frozen_logging_none_std_streams(monkeypatch, tmp_path):
    """Verify _setup_frozen_logging handles None sys.stdout and sys.stderr gracefully."""
    import web.__main__ as web_main
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    with _isolated_frozen_logging_state():
        log_path = web_main._setup_frozen_logging()
        assert log_path is not None
        assert log_path.exists()
