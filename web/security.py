"""Security controls for the AksaraSight Web UI backend.

Enforces loopback-only bindings, Host/Origin header filtering to prevent
DNS rebinding and CSRF attacks, and isolated upload directory path validation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
import urllib.parse
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

# Allowed hosts for loopback access
ALLOWED_HOSTNAMES: frozenset[str] = frozenset({
    "127.0.0.1",
    "localhost",
    "testserver",
    "::1",
    "[::1]",
})

# Maximum upload file size limit: 100 MB
MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024

# Allowed file extensions for document processing
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
})


def validate_loopback_host(host: str) -> None:
    """Refuse to start the server if host is not loopback.

    Args:
        host: Proposed host address string.

    Raises:
        ValueError: If host is not a loopback address.
    """
    clean_host = host.strip().lower()
    if clean_host not in ("127.0.0.1", "localhost", "::1", "[::1]"):
        raise ValueError(
            f"Server host must be loopback (127.0.0.1 or localhost), got: {host}"
        )


def get_upload_dir() -> Path:
    """Return the isolated directory for uploaded document storage.

    Prioritizes:
    1. AKSARA_UPLOAD_DIR environment override (useful for tests or custom scratch).
    2. %LOCALAPPDATA%\\AksaraSight\\web_uploads on Windows.
    3. ~/.local/share/AksaraSight/web_uploads on Linux / macOS.
    """
    env_dir = os.environ.get("AKSARA_UPLOAD_DIR")
    if env_dir:
        upload_path = Path(env_dir).resolve()
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            upload_path = (Path(local_app_data) / "AksaraSight" / "web_uploads").resolve()
        else:
            upload_path = (Path.home() / ".local" / "share" / "AksaraSight" / "web_uploads").resolve()

    upload_path.mkdir(parents=True, exist_ok=True)
    return upload_path


def generate_secure_upload_path(
    filename: str,
    base_dir: Optional[Path] = None,
) -> Path:
    """Generate a sanitized, unique path for storing an uploaded document.

    Generates a UUID4-based filename with sanitized extension and validates
    that the resolved destination path remains strictly inside base_dir.

    Args:
        filename: Original user filename.
        base_dir: Target upload folder (defaults to get_upload_dir()).

    Returns:
        Path: Secure resolved destination file path.

    Raises:
        ValueError: If extension is unsupported or path traversal is detected.
    """
    upload_root = (base_dir or get_upload_dir()).resolve()
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: '{suffix}'")

    unique_filename = f"{uuid.uuid4().hex}{suffix}"
    target_path = (upload_root / unique_filename).resolve()

    if not target_path.is_relative_to(upload_root):
        raise ValueError("Path traversal detected: upload path escaped target directory")

    return target_path


class LoopbackSecurityMiddleware(BaseHTTPMiddleware):
    """Enforces DNS rebinding protection and CSRF loopback origin checks."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 1. Host header validation (DNS Rebinding protection)
        host_header = request.headers.get("host")
        if not host_header:
            return PlainTextResponse("Missing Host header", status_code=400)

        # Handle host:port syntax
        hostname = host_header.split(":")[0].strip().lower()
        if hostname.startswith("[") and "]" in host_header:
            # IPv6 literal with brackets e.g. [::1]:8000
            hostname = host_header.split("]")[0] + "]"
            hostname = hostname.lower()

        if hostname not in ALLOWED_HOSTNAMES:
            return PlainTextResponse("Invalid Host header", status_code=400)

        # 2. Origin validation on state-modifying HTTP methods (CSRF protection)
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin_header = request.headers.get("origin")
            if origin_header:
                try:
                    parsed = urllib.parse.urlsplit(origin_header)
                    origin_host = (parsed.hostname or "").lower()
                    if origin_host not in ALLOWED_HOSTNAMES:
                        return PlainTextResponse(
                            "Forbidden: Cross-origin request rejected", status_code=403
                        )
                except Exception:
                    return PlainTextResponse(
                        "Forbidden: Malformed Origin header", status_code=403
                    )

        return await call_next(request)
