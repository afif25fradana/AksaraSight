"""Runtime management and verified download subsystem for llama.cpp binaries.

Provides automated asset resolution, streaming download with SHA-256 integrity
verification, zip-slip immune extraction, staging isolation, post-install binary
validation, and persistent manifest caching.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Optional
import uuid
import zipfile

import requests

from core.hardware import PINNED_LLAMA_BUILD

logger = logging.getLogger(__name__)

# Official GitHub repository for prebuilt llama.cpp binaries
GITHUB_REPO_OWNER = "ggerganov"
GITHUB_REPO_NAME = "llama.cpp"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"

# Defense-in-depth: Authoritative known-good SHA-256 digests for PINNED_LLAMA_BUILD (b10930)
KNOWN_PINNED_HASHES: Dict[str, str] = {
    "cudart-llama-bin-win-cuda-12.4-x64.zip": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    "llama-b10930-bin-win-cuda-12.4-x64.zip": "7d07deb817f7f380d1da119c76967d7ead0a4dbb02456c0edfda82a99122fed6",
    "llama-b10930-bin-win-vulkan-x64.zip": "ee489d90101575366ec3fcb86f7597ff9b646d09b88c0d83275d5c6ff81374dd",
    "llama-b10930-bin-win-cpu-x64.zip": "a0c1bf04e7b7b4b6c7f280b6bef08ecaa170f2ba611830b2332bce9ddf352dab",
}


# ==============================================================================
# Exceptions Hierarchy
# ==============================================================================

class RuntimeManagerError(Exception):
    """Base exception for all runtime manager operations."""
    pass


class RuntimeDownloadError(RuntimeManagerError):
    """Raised when release asset resolution or download fails."""
    pass


class RuntimeIntegrityError(RuntimeManagerError):
    """Raised when cryptographic digest validation fails."""
    pass


class ZipSlipSecurityError(RuntimeManagerError):
    """Raised when an archive member attempts directory traversal during extraction."""
    pass


class RuntimeValidationError(RuntimeManagerError):
    """Raised when an extracted binary fails post-install sanity execution."""
    pass


# ==============================================================================
# Data Models
# ==============================================================================

@dataclass(frozen=True)
class ReleaseAssetInfo:
    """Metadata describing a downloadable release asset."""
    name: str
    download_url: str
    size: int
    digest: Optional[str] = None  # e.g., 'sha256:<hex>' or '<hex>'


@dataclass(frozen=True)
class InstalledRuntimeInfo:
    """Descriptor for an installed, verified runtime binary."""
    tag: str
    backend: str
    executable_path: Path
    manifest_path: Path


# ==============================================================================
# Directory Resolution
# ==============================================================================

def get_runtime_base_dir() -> Path:
    """Return the root base directory for all managed local runtimes.

    Windows: %LOCALAPPDATA%\\GLM-OCR\\runtimes\\llama-cpp\\
    POSIX:   ~/.local/share/glm-ocr/runtimes/llama-cpp/
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data) / "GLM-OCR" / "runtimes" / "llama-cpp"
        else:
            base = Path.home() / "AppData" / "Local" / "GLM-OCR" / "runtimes" / "llama-cpp"
    else:
        base = Path.home() / ".local" / "share" / "glm-ocr" / "runtimes" / "llama-cpp"

    return base.resolve()


def get_runtime_dir(tag: str = PINNED_LLAMA_BUILD, backend: str = "cuda") -> Path:
    """Return the versioned target directory for a specific build tag and backend."""
    clean_tag = tag.strip()
    clean_backend = backend.strip().lower()
    return get_runtime_base_dir() / f"{clean_tag}-{clean_backend}"


# ==============================================================================
# Asset Resolution
# ==============================================================================

def resolve_required_asset_names(backend: str, tag: str = PINNED_LLAMA_BUILD) -> List[str]:
    """Resolve the required archive filenames for a given backend and build tag.

    Args:
        backend: Runtime backend ('cuda', 'vulkan', 'cpu').
        tag: Pinned GitHub release tag (e.g. 'b10930').

    Returns:
        List[str]: Ordered list of target asset archive names.

    Raises:
        ValueError: If the backend is unsupported.
    """
    clean_backend = backend.strip().lower()
    clean_tag = tag.strip()

    if clean_backend == "cuda":
        # Critical: Windows CUDA builds require both primary runtime and companion cudart DLLs
        return [
            f"llama-{clean_tag}-bin-win-cuda-12.4-x64.zip",
            f"cudart-llama-bin-win-cuda-12.4-x64.zip",
        ]
    elif clean_backend == "vulkan":
        return [f"llama-{clean_tag}-bin-win-vulkan-x64.zip"]
    elif clean_backend == "cpu":
        return [f"llama-{clean_tag}-bin-win-cpu-x64.zip"]
    else:
        raise ValueError(f"Unsupported runtime backend: '{backend}'. Supported: 'cuda', 'vulkan', 'cpu'")


def fetch_release_assets_metadata(
    tag: str = PINNED_LLAMA_BUILD,
    session: Optional[requests.Session] = None,
) -> Dict[str, ReleaseAssetInfo]:
    """Query GitHub Releases API for a specific tagged release and index available assets.

    IMPORTANT: Queries specifically for the pinned tag URL, NEVER 'latest', to prevent
    fetching unreviewed or breaking upstream commits.

    Args:
        tag: Specific release tag (e.g. 'b10930').
        session: Optional HTTP session.

    Returns:
        Dict[str, ReleaseAssetInfo]: Mapping of asset filename to metadata.

    Raises:
        RuntimeDownloadError: If the release cannot be fetched or response is malformed.
    """
    url = f"{GITHUB_API_BASE}/releases/tags/{tag.strip()}"
    http_client = session if session is not None else requests

    headers = {
        "User-Agent": "GLM-OCR-Local-Desktop",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        resp = http_client.get(url, headers=headers, timeout=15.0)
        if resp.status_code == 404:
            raise RuntimeDownloadError(f"Target release tag '{tag}' not found on {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}")
        if resp.status_code == 403:
            raise RuntimeDownloadError(
                "GitHub API rate limit exceeded. Please wait before checking updates or configure custom path."
            )
        resp.raise_for_status()

        data = resp.json()
        raw_assets = data.get("assets", [])
        if not raw_assets:
            raise RuntimeDownloadError(f"No release assets found in release tag '{tag}'")

        assets: Dict[str, ReleaseAssetInfo] = {}
        for item in raw_assets:
            name = item.get("name")
            download_url = item.get("browser_download_url")
            size = item.get("size", 0)
            digest = item.get("digest")

            if name and download_url:
                # Fallback to known pinned hash if GitHub API did not supply digest
                if not digest and name in KNOWN_PINNED_HASHES and tag == PINNED_LLAMA_BUILD:
                    digest = f"sha256:{KNOWN_PINNED_HASHES[name]}"

                assets[name] = ReleaseAssetInfo(
                    name=name,
                    download_url=download_url,
                    size=size,
                    digest=digest,
                )

        return assets

    except requests.exceptions.RequestException as req_err:
        logger.warning("Failed to fetch release assets for %s: %s", tag, req_err)
        raise RuntimeDownloadError(f"Network error querying GitHub releases: {req_err}") from req_err
    except Exception as exc:
        raise RuntimeDownloadError(f"Unexpected error resolving release assets: {exc}") from exc


# ==============================================================================
# Streaming Download with Integrity Verification
# ==============================================================================

def download_and_verify_asset(
    asset: ReleaseAssetInfo,
    dest_dir: Path,
    session: Optional[requests.Session] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Stream download an asset archive, incrementally verify SHA-256, and finalize.

    Strict Order:
    1. Stream chunks to a temporary file (`<name>.part`) in dest_dir.
    2. Incrementally update hashlib.sha256().
    3. Compare computed digest against expected digest BEFORE any extraction.
    4. On mismatch: immediately delete .part file and raise RuntimeIntegrityError.
    5. On match: rename .part to final archive path.

    Args:
        asset: Metadata of asset to download.
        dest_dir: Destination directory.
        session: Optional HTTP session.
        progress_callback: Optional callback receiving (bytes_downloaded, total_bytes).

    Returns:
        Path: Final verified archive file path.

    Raises:
        RuntimeIntegrityError: If SHA-256 does not match expected digest.
        RuntimeDownloadError: On network or disk I/O failure.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    part_path = dest_dir / f"{asset.name}.part"
    final_path = dest_dir / asset.name

    if part_path.exists():
        part_path.unlink()

    http_client = session if session is not None else requests
    headers = {"User-Agent": "GLM-OCR-Local-Desktop"}
    hasher = hashlib.sha256()

    logger.info("Starting download of %s (%s bytes)...", asset.name, asset.size)

    try:
        with http_client.get(asset.download_url, headers=headers, stream=True, timeout=30.0) as resp:
            resp.raise_for_status()
            total_bytes = int(resp.headers.get("Content-Length", asset.size))
            bytes_downloaded = 0

            with open(part_path, "wb") as f_out:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f_out.write(chunk)
                        hasher.update(chunk)
                        bytes_downloaded += len(chunk)
                        if progress_callback:
                            try:
                                progress_callback(bytes_downloaded, total_bytes)
                            except Exception:
                                pass

    except Exception as down_exc:
        if part_path.exists():
            part_path.unlink()
        logger.warning("Download failed for %s: %s", asset.name, down_exc)
        raise RuntimeDownloadError(f"Failed to download {asset.name}: {down_exc}") from down_exc

    # Cryptographic Integrity Verification
    computed_hex = hasher.hexdigest().lower()
    github_hex = asset.digest.split(":")[-1].strip().lower() if asset.digest else None
    pinned_hex = KNOWN_PINNED_HASHES.get(asset.name, "").lower() or None

    # Cross-verify: if both GitHub API digest and pinned hash are available, they MUST match
    if github_hex and pinned_hex and github_hex != pinned_hex:
        if part_path.exists():
            part_path.unlink()
        err_msg = (
            f"Security violation: Digest mismatch between GitHub API digest ({github_hex}) "
            f"and authoritative pinned hash ({pinned_hex}) for '{asset.name}'. Aborting."
        )
        logger.error(err_msg)
        raise RuntimeIntegrityError(err_msg)

    expected_hex = github_hex or pinned_hex

    # FAIL-CLOSED: Refuse unverified extraction if no authoritative hash exists from any source
    if not expected_hex:
        if part_path.exists():
            part_path.unlink()
        err_msg = (
            f"Security violation: No authoritative SHA-256 digest available for '{asset.name}' "
            "(neither GitHub API digest nor hardcoded hash). Refusing unverified extraction."
        )
        logger.error(err_msg)
        raise RuntimeIntegrityError(err_msg)

    if computed_hex != expected_hex:
        if part_path.exists():
            part_path.unlink()
        err_msg = (
            f"SHA-256 integrity verification FAILED for '{asset.name}'. "
            f"Expected: {expected_hex}, Computed: {computed_hex}. Partial download removed."
        )
        logger.error(err_msg)
        raise RuntimeIntegrityError(err_msg)

    logger.info("SHA-256 integrity verified for %s (%s)", asset.name, computed_hex[:12])

    # Finalize download
    if final_path.exists():
        final_path.unlink()
    part_path.rename(final_path)
    return final_path


# ==============================================================================
# Safe Extraction (Zip-Slip Immune)
# ==============================================================================

def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    """Extract a ZIP archive strictly verifying that no member escapes target_dir.

    Args:
        zip_path: Source ZIP file path.
        target_dir: Destination directory.

    Raises:
        ZipSlipSecurityError: If any archive member path attempts directory traversal.
    """
    target_dir_resolved = target_dir.resolve()
    target_dir_resolved.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Pre-flight validation: check ALL members before writing any file
        for member in zf.infolist():
            member_target = (target_dir_resolved / member.filename).resolve()
            try:
                member_target.relative_to(target_dir_resolved)
            except ValueError:
                raise ZipSlipSecurityError(
                    f"Security violation: Zip-slip path traversal attempt in '{zip_path.name}'. "
                    f"Archive member '{member.filename}' escapes target directory."
                )

        # Extraction
        zf.extractall(target_dir_resolved)
        logger.info("Successfully extracted %s into %s", zip_path.name, target_dir_resolved)


# ==============================================================================
# Post-Install Binary Sanity Validation
# ==============================================================================

def validate_runtime_binary(exe_path: Path) -> bool:
    """Execute minimal sanity check to confirm the binary can initialize on this machine.

    Tests that dynamic libraries (e.g. CUDA runtime / Vulkan loaders) resolve properly
    without a fatal DLL loader crash or missing dependency error. Suppresses Windows
    crash-report modal dialogs (WerFault) and enforces a strict 5.0s execution timeout.

    Args:
        exe_path: Path to llama-server executable.

    Returns:
        bool: True if execution succeeded cleanly.
    """
    if not exe_path.is_file():
        return False

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    # Suppress Windows crash-report dialogs (SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX)
    prev_mode = None
    if sys.platform == "win32":
        try:
            import ctypes
            # 0x0001 = SEM_FAILCRITICALERRORS, 0x0002 = SEM_NOGPFAULTERRORBOX
            prev_mode = ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
        except Exception:
            pass

    try:
        # Try --version first, then -h
        for flag in ("--version", "-h"):
            try:
                res = subprocess.run(
                    [str(exe_path), flag],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5.0,
                    creationflags=creationflags,
                )
                if res.returncode == 0:
                    return True
            except subprocess.TimeoutExpired:
                logger.warning("Runtime validation timed out after 5.0s for %s with %s", exe_path, flag)
                # On hang/timeout, abort immediately; do not wait another 5s for -h
                return False
            except Exception as exc:
                logger.debug("Runtime validation check '%s' failed: %s", flag, exc)

        return False
    finally:
        if prev_mode is not None:
            try:
                import ctypes
                ctypes.windll.kernel32.SetErrorMode(prev_mode)
            except Exception:
                pass


# ==============================================================================
# Idempotency & Caching
# ==============================================================================

def is_runtime_installed(tag: str = PINNED_LLAMA_BUILD, backend: str = "cuda") -> bool:
    """Determine whether a valid, verified runtime installation already exists on disk.

    Zero network calls. Validates manifest.json, build tag, and executable presence.

    Args:
        tag: Build tag.
        backend: Runtime backend.

    Returns:
        bool: True if fully installed and ready for immediate launch.
    """
    runtime_dir = get_runtime_dir(tag, backend)
    manifest_path = runtime_dir / "manifest.json"
    exe_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    exe_path = runtime_dir / exe_name

    if not runtime_dir.is_dir() or not manifest_path.is_file() or not exe_path.is_file():
        return False

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_data.get("tag") == tag and manifest_data.get("backend") == backend.lower():
            return True
    except Exception:
        pass

    return False


def get_installed_runtime_path(tag: str = PINNED_LLAMA_BUILD, backend: str = "cuda") -> Optional[Path]:
    """Return the absolute path to the installed llama-server executable, or None."""
    if is_runtime_installed(tag, backend):
        exe_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
        return get_runtime_dir(tag, backend) / exe_name
    return None


# ==============================================================================
# Orchestrator: Ensure Runtime
# ==============================================================================

def ensure_runtime(
    backend: str,
    tag: str = PINNED_LLAMA_BUILD,
    session: Optional[requests.Session] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> Path:
    """Ensure the target runtime is installed and verified, downloading only if needed.

    Orchestration Flow:
    1. Check if valid runtime is already installed on disk -> return immediately if so.
    2. Query GitHub Releases API for the pinned tag metadata.
    3. Stream download each required archive to downloads/ with incremental SHA-256 verification.
    4. Safely extract archives into an isolated temporary staging subdirectory.
    5. Perform post-install sanity check executing `llama-server --version`.
    6. Write manifest.json recording installation metadata.
    7. Atomically rename/move staging subdirectory to final versioned path.
    8. On any failure: clean up staging directory and partial files immediately.

    Args:
        backend: Target backend ('cuda', 'vulkan', 'cpu').
        tag: Pinned release tag.
        session: Optional HTTP session.
        progress_callback: Optional callback(stage_message, bytes_done, total_bytes).

    Returns:
        Path: Path to the ready-to-execute llama-server binary.

    Raises:
        RuntimeManagerError: If resolution, download, extraction, or validation fails.
    """
    clean_backend = backend.strip().lower()
    clean_tag = tag.strip()

    # 1. Idempotency check: Zero network calls if already installed
    existing = get_installed_runtime_path(clean_tag, clean_backend)
    if existing is not None:
        logger.info("Runtime %s-%s already installed at %s", clean_tag, clean_backend, existing)
        return existing

    runtime_dir = get_runtime_dir(clean_tag, clean_backend)
    base_dir = get_runtime_base_dir()
    downloads_dir = base_dir / "downloads"
    staging_dir = base_dir / f"staging_{clean_tag}_{clean_backend}_{uuid.uuid4().hex[:8]}"

    exe_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"

    try:
        # 2. Resolve required assets
        required_names = resolve_required_asset_names(clean_backend, clean_tag)

        if progress_callback:
            progress_callback("Resolving release assets...", 0, 0)

        assets_metadata = fetch_release_assets_metadata(clean_tag, session=session)

        # 3. Download and verify each archive
        downloaded_archives: List[Path] = []
        for asset_name in required_names:
            if asset_name not in assets_metadata:
                raise RuntimeDownloadError(
                    f"Required release asset '{asset_name}' not found in GitHub release '{clean_tag}'"
                )
            asset_info = assets_metadata[asset_name]

            def _asset_progress(done: int, total: int) -> None:
                if progress_callback:
                    progress_callback(f"Downloading {asset_name}...", done, total)

            archive_path = download_and_verify_asset(
                asset=asset_info,
                dest_dir=downloads_dir,
                session=session,
                progress_callback=_asset_progress,
            )
            downloaded_archives.append(archive_path)

        # 4. Safe extraction into temporary staging folder
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        for archive in downloaded_archives:
            if progress_callback:
                progress_callback(f"Extracting {archive.name}...", 0, 0)
            safe_extract_zip(archive, staging_dir)

        # 5. Confirm executable existence
        staging_exe = staging_dir / exe_name
        if not staging_exe.is_file():
            raise RuntimeValidationError(
                f"Extraction completed but executable '{exe_name}' was not found in archive."
            )

        # 6. Post-install validation check
        if progress_callback:
            progress_callback("Verifying runtime binary...", 0, 0)

        if not validate_runtime_binary(staging_exe):
            raise RuntimeValidationError(
                f"Runtime binary verification failed: '{staging_exe}' failed to execute. "
                "Check for missing system dependencies or driver incompatibility."
            )

        # 7. Write manifest.json
        manifest = {
            "tag": clean_tag,
            "backend": clean_backend,
            "executable": exe_name,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "assets": required_names,
        }
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 8. Atomic directory move/replace
        if runtime_dir.exists():
            backup_dir = base_dir / f"{runtime_dir.name}_old_{uuid.uuid4().hex[:6]}"
            runtime_dir.rename(backup_dir)
            try:
                staging_dir.rename(runtime_dir)
                shutil.rmtree(backup_dir, ignore_errors=True)
            except Exception:
                if backup_dir.exists() and not runtime_dir.exists():
                    backup_dir.rename(runtime_dir)
                raise
        else:
            staging_dir.rename(runtime_dir)

        final_exe = runtime_dir / exe_name
        logger.info("Managed runtime successfully installed: %s", final_exe)
        return final_exe

    except Exception as exc:
        # 9. Clean up staging on any failure
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        logger.error("Failed to ensure runtime %s-%s: %s", clean_tag, clean_backend, exc)
        raise
