"""Tests for Web loopback security middleware, origins, and headers."""

from pathlib import Path


from web.app import create_app
from tests.web_fixtures import (
    AsgiClient,
)


def test_loopback_security_middleware_host_validation(tmp_path: Path) -> None:
    """Verify loopback Host enforcement (rejects external hosts, accepts loopback)."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # Valid loopback Hosts
    status, _, _ = client.get("/health", headers={"host": "127.0.0.1"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "127.0.0.1:8000"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "localhost:3000"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "[::1]"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "[::1]:8000"})
    assert status == 200

    # Rejected non-loopback Hosts
    status, _, body = client.get("/health", headers={"host": "attacker.com"})
    assert status == 400
    assert body == b"Bad Request"

    status, _, body = client.get("/health", headers={"host": "192.168.1.10:8000"})
    assert status == 400
    assert body == b"Bad Request"


def test_loopback_security_middleware_origin_validation(tmp_path: Path) -> None:
    """Verify Origin header validation on mutating requests (POST)."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)

    # Valid loopback Origins on POST
    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert status == 404  # Passes middleware, route handles missing job

    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:5173"},
    )
    assert status == 404

    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://[::1]:8000"},
    )
    assert status == 404

    # Sec-Fetch-Site cross-site rejection on POST
    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={
            "sec-fetch-site": "cross-site",
            "origin": "http://127.0.0.1:8000",
        },
    )
    assert status == 403
    assert body == b"Forbidden"

    # Sec-Fetch-Site cross-site permitted on GET (safe method)
    status, _, _ = client.get(
        "/health",
        headers={"sec-fetch-site": "cross-site"},
    )
    assert status == 200

    # Rejected non-loopback Origins on POST
    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://attacker.com"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "https://malicious-site.org:8080"},
    )
    assert status == 403
    assert body == b"Forbidden"


def test_loopback_security_middleware_port_pinning(tmp_path: Path) -> None:
    """Verify port pinning rejects requests from different port origin or host."""
    app = create_app(upload_dir=tmp_path, allowed_port=8000)
    client = AsgiClient(app)

    # 1. Mutating requests (POST) from mismatched origin must be rejected with 403
    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:3000"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # 2. Mutating requests from matching pinned port origin are accepted past middleware
    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert status == 404  # Reached app route

    status, _, _ = client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:8000"},
    )
    assert status == 404

    # 3. Host header with mismatched port is rejected with 400
    status, _, body = client.get("/health", headers={"host": "localhost:3000"})
    assert status == 400
    assert body == b"Bad Request"

    status, _, body = client.get("/health", headers={"host": "127.0.0.1:9000"})
    assert status == 400
    assert body == b"Bad Request"

    # 4. Host header matching pinned port is accepted
    status, _, _ = client.get("/health", headers={"host": "127.0.0.1:8000"})
    assert status == 200

    status, _, _ = client.get("/health", headers={"host": "localhost:8000"})
    assert status == 200


def test_dev_mode_permits_vite_dev_server_origin() -> None:
    """Verify dev_mode allows Vite/React dev origins while production blocks them."""
    # 1. Production mode (dev_mode=False) rejects dev server origins with 403
    prod_app = create_app(allowed_port=8000, dev_mode=False)
    prod_client = AsgiClient(prod_app)
    status, _, body = prod_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = prod_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # Verify Vite dev server proxy header combination is rejected in production
    status, _, body = prod_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"host": "127.0.0.1:8000", "origin": "http://localhost:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # 2. Dev mode (dev_mode=True) permits Vite dev server origins
    dev_app = create_app(allowed_port=8000, dev_mode=True)
    dev_client = AsgiClient(dev_app)
    status, _, _ = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:5173"},
    )
    assert status == 404  # Passes middleware and reaches route handler

    status, _, _ = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://127.0.0.1:5173"},
    )
    assert status == 404

    # Verify Vite dev server proxy header combination is accepted in dev mode
    status, _, _ = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"host": "127.0.0.1:8000", "origin": "http://localhost:5173"},
    )
    assert status == 404

    # Port 3000 is rejected with 403 even in dev mode (dropped per YAGNI)
    status, _, body = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:3000"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # Non-whitelisted port or external origin still rejected in dev mode
    status, _, body = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://localhost:9999"},
    )
    assert status == 403
    assert body == b"Forbidden"

    status, _, body = dev_client.post(
        "/api/documents/nonexistent/cancel",
        headers={"origin": "http://attacker.com:5173"},
    )
    assert status == 403
    assert body == b"Forbidden"


def test_origin_check_covers_all_methods_with_origin(tmp_path: Path) -> None:
    """Verify that any request (mutating or safe) with untrusted Origin is rejected with 403, while requests without Origin pass."""
    app = create_app(upload_dir=tmp_path)
    client = AsgiClient(app)
    bad_origin = {"origin": "http://evil.com"}

    # All methods supplying an untrusted Origin must be rejected with 403
    for method in ("POST", "PUT", "DELETE", "PATCH", "GET", "HEAD", "CUSTOMVERB"):
        status, _, _ = client.request(method, "/api/documents", headers=bad_origin)
        assert status == 403, f"Method {method} with evil origin expected 403 but got {status}"

    # Requests without Origin header succeed for safe methods
    status_get, _, _ = client.request("GET", "/api/documents")
    assert status_get == 200

    status_head, _, _ = client.request("HEAD", "/api/documents")
    assert status_head != 403


test_origin_check_covers_all_non_safe_methods = test_origin_check_covers_all_methods_with_origin


def test_security_headers_present_on_responses(client: AsgiClient) -> None:
    """Verify security headers are injected on all HTTP responses."""
    status, headers, _ = client.get("/health")
    assert status == 200
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("x-content-type-options") == "nosniff"
    assert "frame-ancestors 'none'" in headers.get("content-security-policy", "")
    assert "default-src 'self'" in headers.get("content-security-policy", "")


def test_sec_fetch_site_cross_site_blocked_on_api_endpoints(client: AsgiClient) -> None:
    """Verify Sec-Fetch-Site: cross-site is rejected on /api/ endpoints even for GET and HEAD."""
    # 1. GET /api/documents with cross-site fetch site is blocked
    status, _, body = client.get(
        "/api/documents",
        headers={"sec-fetch-site": "cross-site"},
    )
    assert status == 403
    assert body == b"Forbidden"

    # 2. HEAD /api/documents with cross-site fetch site is blocked
    status, _, body = client.request(
        "HEAD",
        "/api/documents",
        headers={"sec-fetch-site": "cross-site"},
    )
    assert status == 403

    # 3. Non-api path with cross-site fetch site is permitted
    status, _, _ = client.get(
        "/health",
        headers={"sec-fetch-site": "cross-site"},
    )
    assert status == 200
