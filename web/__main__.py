"""CLI entrypoint for AksaraSight Web UI server."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Optional
from urllib.parse import urlsplit
import webbrowser

import uvicorn

from core.constants import __version__
from core.hardware import _probe_wsl
from web.app import SSEShutdownSupervisor, create_app, enforce_loopback_host

_original_uvicorn_run = uvicorn.run


def _fatal_gui_error(title: str, message: str) -> None:
    """Report fatal startup error to logs, native Win32 dialog if frozen, and stderr."""
    logging.getLogger("crash").critical("%s: %s", title, message)
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, f"AksaraSight - {title}", 0x10)
        except Exception:
            pass
    elif sys.stderr:
        sys.stderr.write(f"Error: {message}\n")
    sys.exit(1)


def find_browser_executable() -> Optional[str]:
    """Resolve a Chromium-family browser executable for app-mode launching, or None for fallback."""
    if sys.platform == "win32":
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        prog = os.environ.get("ProgramFiles", r"C:\Program Files")
        local_app = os.environ.get("LocalAppData", r"C:\Users\Default\AppData\Local")
        candidates = [
            os.path.join(prog_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(prog, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(prog, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(prog_x86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        try:
            import winreg
            for app in ("msedge.exe", "chrome.exe", "brave.exe"):
                for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app}") as k:
                            val, _ = winreg.QueryValueEx(k, "")
                            if val and os.path.isfile(val):
                                return val
                    except OSError:
                        pass
        except (ImportError, OSError):
            pass
        return None

    # Linux / macOS
    if sys.platform != "win32":
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return None
        for bin_name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            found = shutil.which(bin_name)
            if found:
                return found
    return None


def _launch_desktop_window(url: str, port: int) -> None:
    """Launch browser in app-mode window with isolated profile, or fall back to default browser."""
    browser_exe = find_browser_executable()
    if not browser_exe:
        _open_browser(url)
        return

    if sys.platform == "win32":
        base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        profile_dir = base_dir / "AksaraSight" / "browser_profile"
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME")
        base_dir = Path(xdg_state) if xdg_state and xdg_state.strip() else (Path.home() / ".local" / "state")
        profile_dir = base_dir / "aksarasight" / "browser_profile"

    profile_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        browser_exe,
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    try:
        subprocess.Popen(cmd)
    except Exception as e:
        logging.getLogger("app").warning(
            "Failed to launch app-mode browser (%s); falling back to default: %s", browser_exe, e
        )
        _open_browser(url)


def _wait_and_launch(url: str, host: str, port: int, timeout: float = 5.0) -> None:
    """Poll loopback port until web server is bound, then launch the desktop window."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    _launch_desktop_window(url, port)


def _setup_frozen_logging() -> Optional[Path]:
    """Configure file-based and console logging when running as a frozen executable.

    Only active when running inside a PyInstaller frozen bundle
    (getattr(sys, 'frozen', False) is True). Captures unhandled
    exceptions via sys.excepthook to %LOCALAPPDATA%\\AksaraSight\\logs\\app.log.
    """
    if not getattr(sys, "frozen", False):
        return None

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    logging.getLogger("web").setLevel(logging.DEBUG)
    logging.getLogger("core").setLevel(logging.DEBUG)

    # 1. Attach console StreamHandler if sys.stdout is available (before devnull fallback)
    if sys.stdout is not None:
        has_stream_handler = any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in root_logger.handlers
        )
        if not has_stream_handler:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(
                logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
            )
            root_logger.addHandler(console_handler)

    # 2. Safe devnull redirection if stdin, stdout or stderr are None
    if sys.stdin is None:
        try:
            sys.stdin = open(os.devnull, "r")
        except OSError:
            pass
    if sys.stdout is None:
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
    if sys.stderr is None:
        try:
            sys.stderr = open(os.devnull, "w")
        except OSError:
            pass

    # 3. FileHandler targeting %LOCALAPPDATA%\AksaraSight\logs\app.log with OSError resilience
    log_file: Optional[Path] = None
    try:
        app_data = os.environ.get("LOCALAPPDATA")
        if app_data:
            base_dir = Path(app_data)
            log_dir = base_dir / "AksaraSight" / "logs"
        elif sys.platform != "win32":
            xdg_state = os.environ.get("XDG_STATE_HOME")
            base_dir = Path(xdg_state) if xdg_state else (Path.home() / ".local" / "state")
            log_dir = base_dir / "aksarasight" / "logs"
        else:
            base_dir = Path.home() / "AppData" / "Local"
            log_dir = base_dir / "AksaraSight" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        candidate_log_file = log_dir / "app.log"

        has_file_handler = any(
            isinstance(h, logging.FileHandler)
            and getattr(h, "baseFilename", None) == str(candidate_log_file.resolve())
            for h in root_logger.handlers
        )
        if not has_file_handler:
            file_handler = RotatingFileHandler(
                str(candidate_log_file),
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
                mode="a",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
            )
            root_logger.addHandler(file_handler)

        log_file = candidate_log_file
    except OSError:
        pass

    # 4. Install sys.excepthook to log unhandled crashes
    def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("crash").critical(
            "Unhandled exception in frozen Web UI runtime",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _handle_unhandled_exception
    logging.getLogger("app").info("Frozen application started (v%s)", __version__)

    return log_file


def _open_browser(url: str) -> None:
    """Open URL in the user's default browser with WSL host bridging support."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return
        if any(ord(c) < 32 or c in "\r\n\0 " for c in url):
            return
    except Exception:
        return

    if (
        sys.platform != "win32"
        and not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
        and _probe_wsl()
    ):
        if shutil.which("wslview"):
            subprocess.run(["wslview", "--", url], check=False)
            return
        if shutil.which("powershell.exe"):
            safe_url = url.replace("'", "''")
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"Start-Process '{safe_url}'"],
                check=False,
            )
            return
    webbrowser.open(url)



def is_port_in_use(host: str, port: int) -> bool:
    """Check if host:port is already bound by another process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the CLI argument parser for the Web UI server."""
    parser = argparse.ArgumentParser(
        prog="python -m web",
        description="Launch AksaraSight Web UI local server.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1). Strictly requires loopback ('127.0.0.1' or 'localhost').",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind port (default: 8000).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable development mode (permits Vite dev server origins like localhost:5173)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the default web browser on startup.",
    )
    return parser


def main() -> None:
    """Parse CLI flags, enforce loopback binding, and run the uvicorn web server."""
    multiprocessing.freeze_support()
    _setup_frozen_logging()
    parser = build_parser()
    args = parser.parse_args()

    try:
        enforce_loopback_host(args.host)
    except ValueError as e:
        _fatal_gui_error("Configuration Error", str(e))

    if is_port_in_use(args.host, args.port):
        _fatal_gui_error("Port In Use", f"Port {args.port} is already in use by another process.")

    if args.dev:
        os.environ["AKSARA_WEB_DEV_MODE"] = "1"

    if getattr(sys, "frozen", False) and not args.no_browser:
        should_open = True
        if sys.platform != "win32":
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and not _probe_wsl():
                should_open = False
                logging.getLogger("app").debug("Headless Linux detected; suppressing browser auto-open")
        if should_open:
            timer = threading.Timer(
                0.0,
                lambda: _wait_and_launch(f"http://{args.host}:{args.port}", args.host, args.port),
            )
            timer.daemon = True
            timer.start()

    if args.reload:
        os.environ["AKSARA_WEB_PORT"] = str(args.port)
        uvicorn.run(
            "web.app:create_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )
    else:
        app = create_app(allowed_port=args.port, dev_mode=args.dev)
        uvicorn_kwargs: dict[str, Any] = {
            "host": args.host,
            "port": args.port,
            "timeout_graceful_shutdown": 3.0,
        }
        if getattr(sys, "frozen", False):
            uvicorn_kwargs["log_config"] = None

        config = uvicorn.Config(app, **uvicorn_kwargs)
        server = uvicorn.Server(config=config)

        orch = getattr(getattr(app, "state", None), "orchestrator", None)
        if not args.no_browser and not args.dev and orch is not None:
            supervisor = SSEShutdownSupervisor(server=server, orchestrator=orch)
            app.state.shutdown_supervisor = supervisor

        if uvicorn.run is not _original_uvicorn_run:
            uvicorn.run(app, **uvicorn_kwargs)
        else:
            server.run()


if __name__ == "__main__":
    main()
