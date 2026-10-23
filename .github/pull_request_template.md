## Summary

Provide a concise summary of the changes made and the motivation behind them.

Fixes #(issue)

## Architectural & Security Invariants

- [ ] **Offline-First**: Does NOT introduce external network requests, telemetry, or remote cloud fallbacks.
- [ ] **Loopback Isolation**: Preserves local-only binding (`127.0.0.1` / `localhost`) and origin security checks.
- [ ] **PDFium Thread-Safety**: PDF operations remain guarded by `_PDFIUM_LOCK` if pipeline code was modified.

## Verification Checklist

Please verify that all applicable tests pass locally before submitting:

- [ ] `python -m pytest` passes completely.
- [ ] `ruff check .` reports no lint errors.
- [ ] `cd frontend && npm test` passes (if frontend was touched).
- [ ] `cd frontend && npm run lint` passes with no TypeScript errors (if frontend was touched).
- [ ] If `frontend/src` was modified, ran `npm run build` so `web/static/` is in sync.
- [ ] Updated documentation (`README.md`, `TECHNICAL.md`, or `docs/adr/`) if behavior changed.
