# ADR-0006: Cross-Platform Support, Packaging Distribution, and CI Governance

## Status
Accepted

## Date
2026-11-13

## Context
AksaraSight runs OCR across Windows 10/11 x64 and Linux x86_64 (native desktop distributions and WSL2) on Python 3.12 and 3.14. Maintaining cross-platform distribution and testing infrastructure requires addressing several operational constraints:
1. **Host-Independent Portable Distribution**: End users should not be required to install system Python runtimes, node packages, or virtual environments. Packaging must generate standalone binaries that bundle all required interpreters and dependencies cleanly.
2. **Structural Cross-OS Test Coverage Variance**: AksaraSight incorporates deep Win32 integrations (Win32 Job Objects in `core/job_object.py`, Windows hardware DLL probing via `ctypes` in `core/hardware.py`, Windows error suppression via `SetErrorMode`). On Linux CI runners (`ubuntu-latest`), these ~150 platform-specific statements are skipped by design. Enforcing a single uniform 90% coverage threshold across all platforms causes false-negative build failures on Linux despite 100% test pass rates.
3. **Automated Dependency Updates & Minified Asset Drift**: Dependabot updates frontend npm dependencies (`frontend/package.json`), but GitHub's Dependabot runner cannot compile TypeScript or execute Vite build tools. This creates drift between source assets and the committed production bundle (`web/static/`), risking broken releases.
4. **Over-Permissive CI Permissions**: Granting `contents: write` permissions across all lint jobs or untrusted pull requests introduces supply-chain security risks. Additionally, regex-based commit message matching (`grep -iqE "dependabot"`) introduces false positives.
5. **Auto-Merge API Rejections**: GitHub's `enablePullRequestAutoMerge` GraphQL mutation rejects auto-merge commands when the target branch (`main`) lacks Branch Protection Rules, halting automated dependency maintenance.
6. **Process-Global Test State Leakage & Mock Drift**: Validating frozen logging entrypoints mutated `logging.getLogger().handlers`, `sys.excepthook`, and `sys.stdout`/`sys.stderr`, leaking file descriptors to `app.log` across test executions. Permissive mocks without signature enforcement allowed tests to pass despite signature drift.

## Decision
1. **Dual-Platform Portable Packaging Pipeline (`scripts/build_portable.py`)**:
   - Use PyInstaller to compile standalone executables:
     - **Windows**: Build `AksaraSight.exe` (Web UI launcher) and `AksaraSight-CLI.exe` with application icons. Package into `AksaraSight-v<version>-windows-x64.zip`.
     - **Linux**: Build ELF binaries `AksaraSight` and `AksaraSight-CLI` without `.exe` suffixes or `.ico` assets. Package into `AksaraSight-v<version>-linux-x64.tar.gz` rooted at `AksaraSight/`, preserving `0o755` executable permissions and normalizing archive root ownership (`uid=0, gid=0`).
   - Provide an automated frozen build verification script (`scripts/verify_frozen_build.py`) validating frozen CLI execution and headless Web UI server initialization before release distribution.
2. **Two-Tiered Cross-OS Coverage Governance**:
   - Establish `fail_under = 86` in `.coveragerc` as the cross-OS global baseline covering portable runtime paths.
   - Enforce `--cov-fail-under=89` explicitly on Windows test matrix jobs in CI (`tests.yml` and `weekly.yml`) where Win32-specific subsystems are fully exercised.
3. **Decoupled Maintenance & Static Bundle Synchronization**:
   - Downgrade `lint` job permissions in `.github/workflows/tests.yml` to read-only (`contents: read`).
   - Extract frontend static bundle auto-compilation into a separate, dedicated CI job (`sync-static-bundle`) with `contents: write` permissions.
   - Gate execution strictly on push events to `main` where the actor or head commit author is `dependabot[bot]`. Developer pushes bypass auto-commit logic entirely.
4. **Branch Protection Status Check Gate with Admin Bypass**:
   - Configure a GitHub Branch Protection Rule on `main` requiring core status checks (`Lint & Code Style` and `Windows Python 3.14 (Full Test Suite)`).
   - Set `enforce_admins: false` and `required_pull_request_reviews: null` to allow automated merges in a solo maintainer workflow without review deadlocks. Enable `delete_branch_on_merge: true` in repository settings.
   - Add defensive fallback warning handling in `.github/workflows/dependabot-automerge.yml` to prevent unhandled GraphQL exceptions from failing the workflow.
5. **Test Suite Invariant Enforcement & Anti-Mock Drift**:
   - Enforce `autospec=True` across `OCREngine` mocks in `tests/test_cli.py` to prevent mock interface drift.
   - Encapsulate frozen entrypoint tests within a scoped `@contextlib.contextmanager` (`_isolated_frozen_logging_state()`) in `tests/test_web_entrypoint.py` and `tests/web_fixtures.py`, deterministically closing and detaching file handlers, restoring redirected streams, and resetting root logger state upon test exit.
   - Configure loggers `"web"` and `"core"` at `logging.DEBUG` while maintaining `root_logger` at `logging.INFO`.
   - Update `MockEngine.process_document` to return an aborted `OCRResult` on offline failure, matching `OCREngine`.
   - Update `MockModelDownloader.download()` to reset `is_downloading = False` and return `False` on cancellation.

## Alternatives Considered & Rejected
- **Uniform 90% Coverage Requirement Across All Operating Systems**: Rejected because platform-specific Win32 modules (`job_object.py`) cannot and should not execute on Linux runners. Lowering the global threshold to 86% while holding Windows to 89% accurately reflects platform realities.
- **Running `npm run build` Inside Dependabot PRs Directly**: Rejected because Dependabot lacks GitHub token permissions to push back to its own PR branch, and running compile-and-commit inside lint jobs violated the principle of least privilege.
- **Mandating Pull Request Approvals on `main`**: Rejected because in a solo maintainer repository, requiring approving reviews creates self-merge deadlocks on automated dependency updates without providing security benefits.
- **Custom Polling Script for Pull Request Merging**: Rejected because GitHub's native `enablePullRequestAutoMerge` feature natively handles queueing, test status monitoring, and merge execution once branch protection rules are configured.
- **Separate Mock Specification Classes**: Rejected because `unittest.mock.patch(..., autospec=True)` natively introspects `OCREngine` with zero maintenance overhead.

## Consequences
- Standalone portable executables are generated for Windows and Linux with zero host Python requirements.
- Dependabot minor and patch updates for actions and npm dependencies automatically merge safely once CI passes, eliminating manual maintenance overhead.
- Frontend static asset bundles remain synchronized on `main` without risking accidental developer push overrides or token leakage.
- CI workflows enforce strict coverage regressions without generating false-positive failures on non-Windows platforms.
- Test suites strictly mirror production engine contracts with zero handle leaks or mock drift.
- Requires maintaining dual-platform build scripts and running CI test matrices across Windows and Linux on both Python 3.12 and 3.14.
