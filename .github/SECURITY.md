# Security Policy

AksaraSight takes the privacy and security of local document processing seriously. Because AksaraSight is explicitly designed to handle confidential documents (legal papers, tax forms, personal notes) offline on local machines, security vulnerabilities that could compromise loopback isolation or local files are treated with high priority.

## Supported Versions

Only the latest release on the `main` branch receives security updates.

| Version | Supported |
|---|---|
| Latest Release (>= 1.3.1) | :white_check_mark: |
| Older releases | :x: |

---

## Threat Model & Scope

### In Scope
- **Loopback Isolation Bypasses**: Cross-Site Request Forgery (CSRF), Cross-Origin Resource Sharing (CORS) misconfigurations, or DNS rebinding that allows an external website visited in a browser to trigger OCR extraction or access exported documents on `127.0.0.1:8000`.
- **Path Traversal & Arbitrary File Writes**: Flaws in multipart file upload, temporary raster caches, or export routines (`/api/documents`, `/api/output`) allowing writes outside intended temporary directories.
- **Subprocess Escapes**: Command injection or unconstrained execution when launching managed `llama-server` instances.
- **Decompression / Pixel Bombs**: Maliciously crafted PDFs or image files designed to bypass `MAX_RASTER_PIXELS` (89,478,485 pixels) and cause unconstrained host memory denial of service.

### Out of Scope
- Attacks requiring prior physical access or administrator/root compromise of the host operating system.
- Attacks occurring when the user explicitly opts out of loopback security via `--allow-remote` or `OCR_ALLOW_REMOTE=true`.
- Upstream vulnerabilities in llama.cpp, Python, or model weights that do not stem from AksaraSight's integration layer.

---

## Reporting a Vulnerability

Please **DO NOT** report security vulnerabilities via public GitHub issues, public pull requests, or social media.

Instead, report vulnerabilities privately using **GitHub Private Vulnerability Reporting**:

👉 **[Submit a Private Security Advisory](https://github.com/afif25fradana/AksaraSight/security/advisories/new)**

### What to Include in Your Report
- A detailed description of the vulnerability and its potential security impact.
- Clear step-by-step reproduction instructions or a minimal Proof of Concept (PoC).
- The operating system and version of AksaraSight where the issue was observed.

### Response & Timeline
AksaraSight is maintained as an independent personal project by [@afif25fradana](https://github.com/afif25fradana). Reports are reviewed within reasonable personal bandwidth (typically within 48–72 hours). Valid reports will receive a coordinated fix and credit in the subsequent release notes.
