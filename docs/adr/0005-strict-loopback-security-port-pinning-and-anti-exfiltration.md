# ADR-0005: Strict Loopback Security, Port Pinning, and Anti-Exfiltration

## Status
Accepted

## Date
2026-10-18

## Context
AksaraSight processes private and sensitive documents (financial statements, legal agreements, medical records). Running a local web server (FastAPI) and an inference endpoint on a workstation creates exposure to local network snooping, DNS rebinding, cross-origin web script attacks, or proxy interception.

## Decision
Enforce defense-in-depth security invariants across configuration, networking, and HTTP sessions:
1. **Loopback Gate**: `Settings` enforces that endpoints point strictly to loopback addresses (`localhost`, `127.0.0.1`, `[::1]`) unless `allow_remote=True` is explicitly configured.
2. **Security Middleware & Browser Headers**: `LoopbackSecurityMiddleware` validates `Host` headers, pins incoming requests to the bound port, rejects all cross-site requests (`Sec-Fetch-Site: cross-site`) targeting `/api/` endpoints with HTTP 403 Forbidden, and injects hardening response headers:
   - `X-Frame-Options: DENY` (clickjacking defense)
   - `X-Content-Type-Options: nosniff` (MIME sniffing defense)
   - `Content-Security-Policy: frame-ancestors 'none'; default-src 'self' 'unsafe-inline' data: blob:` (asset isolation)
3. **Proxy Interception Defense**: Disable environment proxies (`trust_env = False`) on all internal `requests.Session` instances (including ephemeral probe sessions in `probe_server_health`) to prevent system `HTTP_PROXY` variables from routing local inference traffic through remote proxies.
4. **Path & Filename Sanitization**: Relativize file paths in JSON outputs, sanitize error messages to avoid disclosing user account names or local filesystem hierarchies, and sanitize export stems with `sanitize_filename_stem` to defend against Windows reserved DOS device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9).

## Alternatives Considered & Rejected
- **Standard CORS Headers Alone**: Rejected because CORS headers do not protect against simple requests, direct local network access, or DNS rebinding.
- **User Authentication / JWT Passwords**: Rejected as over-engineered complexity for a single-user desktop tool running locally on a personal workstation.

## Consequences
- Documents and OCR transcriptions never leave the local workstation.
- Protects the local server from browser-based drive-by attacks originating from malicious websites open in other tabs.
- Transparent security notice modal warns users before allowing any non-loopback network connection.
