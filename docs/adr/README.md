# Architectural Decision Records (ADRs)

This directory contains the Living Domain Architecture Decision Records for AksaraSight, formatted according to the Michael Nygard standard. Each domain file is maintained in place as decisions evolve, with superseded revisions preserved in Git history (`git log`).

| ADR | Title | Status | Date | Primary Subject |
|:---|:---|:---:|:---:|:---|
| [ADR-0001](./0001-decoupled-local-inference-managed-runtimes-and-subprocess-supervision.md) | Decoupled Local Inference, Managed Runtimes, and Subprocess Supervision | Accepted | 2026-11-13 | Local Inference, Runtime Management & Process Supervision |
| [ADR-0002](./0002-document-ingestion-thread-safe-pdfium-rasterization-and-core-pipeline.md) | Document Ingestion, Thread-Safe PDFium Rasterization, and Core Pipeline | Accepted | 2026-11-13 | Ingestion, Rasterization Mutex & Processing Pipeline |
| [ADR-0003](./0003-presentation-architecture-web-ui-workspace-and-accessibility.md) | Presentation Architecture: Web UI Workspace and Accessibility | Accepted | 2026-11-13 | Web Workspace, SPA Ergonomics & WCAG AA Accessibility |
| [ADR-0004](./0004-web-application-orchestration-event-loop-offloading-and-concurrency.md) | Web Application Orchestration, Event Loop Offloading, and Concurrency | Accepted | 2026-11-13 | Async Offloading, Run-Token Queue & Resource Bounding |
| [ADR-0005](./0005-defense-in-depth-security-loopback-boundary-and-anti-exfiltration.md) | Defense-in-Depth Security, Loopback Boundary, and Anti-Exfiltration | Accepted | 2026-11-13 | Loopback Binding, Header Filtering & Security Boundary |
| [ADR-0006](./0006-cross-platform-support-packaging-distribution-and-ci-governance.md) | Cross-Platform Support, Packaging Distribution, and CI Governance | Accepted | 2026-11-13 | Multi-OS Packaging, Test Matrices & CI/CD Governance |
