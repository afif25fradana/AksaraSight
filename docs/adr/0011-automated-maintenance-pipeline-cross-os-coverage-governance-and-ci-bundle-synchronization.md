# ADR-0011: Automated Maintenance Pipeline, Cross-OS Coverage Governance, and CI Bundle Synchronization

## Status
Accepted

## Date
2026-10-29

## Context
1. **Automated Dependency Updates & Minified Asset Drift**: Dependabot regularly updates frontend npm dependencies (`frontend/package.json` and `package-lock.json`), but GitHub's Dependabot runner cannot compile TypeScript or execute Vite build tools. This creates drift between source assets and the committed production bundle (`web/static/`), leading to CI failures unless the compiled bundle is synchronized.
2. **Over-Permissive CI Permissions & False Trigger Hazards**: In `.github/workflows/tests.yml`, the `lint` job held `contents: write` permissions across all runs (including untrusted pull requests) to facilitate auto-committing drifted static bundles. Furthermore, regex-based commit message matching (`grep -iqE "dependabot"`) introduced false positives, where a developer commit mentioning "dependabot" could trigger unexpected automated git commits.
3. **Structural Cross-OS Test Coverage Variance**: AksaraSight contains core operating system integrations (such as Win32 Job Objects in `core/job_object.py`, Windows hardware DLL probing via `ctypes` in `core/hardware.py`, and Windows error suppression via `SetErrorMode`). On Linux CI runners (`ubuntu-latest`), these ~150 platform-specific statements are skipped by design. Consequently, enforcing a single high coverage threshold (e.g., 90%) uniformly across all operating systems causes false-negative build failures on Linux despite 100% test pass rates.
4. **GitHub Auto-Merge GraphQL Rejections on Unprotected Branches**: The GitHub CLI command `gh pr merge --auto` utilizes the `enablePullRequestAutoMerge` GraphQL mutation. GitHub's auto-merge architecture requires the target base branch (`main`) to possess an active Branch Protection Rule or Ruleset. When `main` is completely unprotected, GitHub API rejects the auto-merge command with `GraphQL: Pull request Protected branch rules not configured for this branch`, halting Dependabot workflows.
5. **SSE Lifecycle Contract Drift & Cold-Start Latency**: The documented Server-Sent Events (SSE) schemas in `TECHNICAL.md` diverged from the actual payloads broadcast by `web/orchestrator.py` (specifically missing `total_pages` in `completed` events and carrying outdated property shapes for `started` and `page_progress`). Additionally, initial document processing incurred cold-start hardware probing latency if not explicitly pre-warmed.
6. **Process-Global Logging State Pollution in Tests**: Tests validating frozen logging entrypoints in `web/__main__.py` mutated `logging.getLogger().handlers`, `sys.excepthook`, and `sys.stdout`/`sys.stderr`. Without deterministic isolation and handle closure, open file descriptors to `app.log` and `os.devnull` leaked across test executions.

## Decision
1. **Decoupled Read-Only Linting and Gated Static Bundle Synchronization**:
   - Downgrade `lint` job permissions in `.github/workflows/tests.yml` to read-only (`contents: read`).
   - Extract static bundle auto-compilation into a separate, dedicated job (`sync-static-bundle`) with `contents: write` permissions.
   - Gate execution strictly on push events to `main` where the actor or head commit author is `dependabot[bot]`. Developer pushes bypass auto-commit logic entirely.
2. **Branch Protection Status Check Gate with Admin Bypass**:
   - Configure a GitHub Branch Protection Rule on `main` requiring core status checks (`Lint & Code Style` and `Windows Python 3.14 (Full Test Suite)`).
   - Set `enforce_admins: false` and `required_pull_request_reviews: null` to preserve developer velocity for solo maintenance without review deadlocks.
   - Enable `delete_branch_on_merge: true` in repository settings to automatically clean up merged feature and dependency branches.
   - Add defensive fallback warning handling in `.github/workflows/dependabot-automerge.yml` to prevent unhandled GraphQL exceptions from failing the workflow.
3. **Two-Tiered Cross-OS Coverage Governance**:
   - Establish `fail_under = 86` in `.coveragerc` as the cross-OS global baseline covering portable runtime paths.
   - Enforce `--cov-fail-under=89` explicitly on Windows test matrix jobs in CI (`tests.yml` and `weekly.yml`) where Win32-specific subsystems are fully exercised.
4. **Contract-Aligned SSE Payload Schemas & Lifespan Pre-warming**:
   - Align `web/orchestrator.py` and `TECHNICAL.md` by including `"total_pages": job.page_count` in the `completed` event payload and documenting exact runtime schemas for `started`, `page_progress`, `cancelled`, and `queued`.
   - Call `start_hardware_prewarm()` asynchronously during `lifespan` startup in `web/app.py` when loopback security is active, ensuring hardware backends are probed prior to receiving user jobs.
5. **Isolated Frozen Logging Teardown**:
   - Encapsulate frozen entrypoint tests within a scoped `@contextlib.contextmanager` (`_isolated_frozen_logging_state()`) in `tests/test_web_api.py`.
   - Deterministically close and detach all newly instantiated file handlers, close redirected `os.devnull` streams, and restore root logger handlers, logging levels, and `sys.excepthook` upon test exit.

## Alternatives Considered & Rejected
- **Uniform 90% Coverage Requirement Across All Operating Systems**: Rejected because platform-specific Win32 modules (`job_object.py`) cannot and should not execute on Linux runners. Lowering the global threshold to 86% while holding Windows to 89% accurately reflects platform realities.
- **Running `npm run build` Inside Dependabot PRs Directly**: Rejected because Dependabot lacks GitHub token permissions to push back to its own PR branch, and running compile-and-commit inside lint jobs violated the principle of least privilege.
- **Mandating Pull Request Approvals on `main`**: Rejected because in a solo maintainer repository, requiring approving reviews creates self-merge deadlocks on automated dependency updates without providing security benefits.
- **Custom Polling Script for Pull Request Merging**: Rejected because GitHub's native `enablePullRequestAutoMerge` feature natively handles queueing, test status monitoring, and merge execution once branch protection rules are configured.

## Consequences
- Dependabot minor and patch updates for actions and npm dependencies automatically merge safely once CI passes, eliminating manual maintenance overhead.
- Frontend static asset bundles remain synchronized with dependencies on `main` without risking accidental developer push overrides or token leakage in PR workflows.
- CI workflows enforce strict coverage regressions without generating false-positive failures on non-Windows platforms.
- Server-Sent Events contracts are authoritative, machine-verified by frontend and backend test suites, and documented accurately in `TECHNICAL.md`.
