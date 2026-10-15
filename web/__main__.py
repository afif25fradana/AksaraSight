"""CLI entrypoint for AksaraSight Web UI server."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
from typing import Any, Optional
import webbrowser

import uvicorn

from core.constants import __version__
from web.app import create_app, enforce_loopback_host


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

    # 2. Safe devnull redirection if stdout or stderr are None
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
        base_dir = Path(app_data) if app_data else (Path.home() / "AppData" / "Local")
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
    _setup_frozen_logging()
    parser = build_parser()
    args = parser.parse_args()

    try:
        enforce_loopback_host(args.host)
    except ValueError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

    if is_port_in_use(args.host, args.port):
        sys.stderr.write(f"Error: Port {args.port} is already in use by another process.\n")
        sys.exit(1)

    if args.dev:
        os.environ["AKSARA_WEB_DEV_MODE"] = "1"

    if getattr(sys, "frozen", False) and not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

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
        uvicorn_kwargs: dict[str, Any] = {"host": args.host, "port": args.port}
        if getattr(sys, "frozen", False):
            uvicorn_kwargs["log_config"] = None
        uvicorn.run(app, **uvicorn_kwargs)


if __name__ == "__main__":
    main()
