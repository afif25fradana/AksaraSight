"""CLI entrypoint for AksaraSight Web UI server."""

import argparse
import os
import sys

import uvicorn

from web.app import create_app, enforce_loopback_host


def main() -> None:
    """Parse CLI flags, enforce loopback binding, and run the uvicorn web server."""
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

    args = parser.parse_args()

    try:
        enforce_loopback_host(args.host)
    except ValueError as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)

    if args.dev:
        os.environ["AKSARA_WEB_DEV_MODE"] = "1"

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
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
