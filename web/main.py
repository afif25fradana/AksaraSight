"""Entrypoint CLI for AksaraSight Web UI backend."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

import uvicorn

from web.security import validate_loopback_host


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Parse command line arguments and launch the uvicorn web server."""
    parser = argparse.ArgumentParser(description="AksaraSight Web UI Server")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Loopback address to bind the server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number to bind the server to (default: 8000)",
    )
    args = parser.parse_args(argv)

    validate_loopback_host(args.host)
    uvicorn.run("web.app:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
