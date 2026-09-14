"""Unit and functional tests for the runtime manager and verified downloader."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch
import zipfile

import pytest
import requests

from core.hardware import PINNED_LLAMA_BUILD
from core.runtime_manager import (
    InstalledRuntimeInfo,
    ReleaseAssetInfo,
    RuntimeDownloadError,
    RuntimeIntegrityError,
    RuntimeManagerError,
    RuntimeValidationError,
    ZipSlipSecurityError,
    download_and_verify_asset,
    ensure_runtime,
    fetch_release_assets_metadata,
    get_installed_runtime_path,
    get_runtime_base_dir,
    get_runtime_dir,
    is_runtime_installed,
    resolve_required_asset_names,
    safe_extract_zip,
    validate_runtime_binary,
)


def _create_test_zip(files: dict[str, bytes]) -> bytes:
    """Helper to create an in-memory zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ==============================================================================
# Asset Resolution Tests
# ==============================================================================

def test_resolve_required_asset_names() -> None:
    """Verify correct archive mapping per backend."""
    # CUDA requires companion cudart
    cuda_assets = resolve_required_asset_names("cuda", "b10930")
    assert len(cuda_assets) == 2
    assert "llama-b10930-bin-win-cuda-12.4-x64.zip" in cuda_assets
    assert "cudart-llama-bin-win-cuda-12.4-x64.zip" in cuda_assets

    # Vulkan is self-contained
    vulkan_assets = resolve_required_asset_names("vulkan", "b10930")
    assert vulkan_assets == ["llama-b10930-bin-win-vulkan-x64.zip"]

    # CPU is self-contained
    cpu_assets = resolve_required_asset_names("cpu", "b10930")
    assert cpu_assets == ["llama-b10930-bin-win-cpu-x64.zip"]

    with pytest.raises(ValueError, match="Unsupported runtime backend"):
        resolve_required_asset_names("metal", "b10930")


# ==============================================================================
# Release Metadata Fetching Tests
# ==============================================================================

def test_fetch_release_assets_metadata_success() -> None:
    """Verify release metadata parsing and digest resolution."""
    mock_payload = {
        "tag_name": "b10930",
        "assets": [
            {
                "name": "llama-b10930-bin-win-vulkan-x64.zip",
                "browser_download_url": "https://github.com/mock/download/vulkan.zip",
                "size": 31675441,
                "digest": "sha256:ee489d90101575366ec3fcb86f7597ff9b646d09b88c0d83275d5c6ff81374dd",
            },
            {
                "name": "llama-b10930-bin-win-cpu-x64.zip",
                "browser_download_url": "https://github.com/mock/download/cpu.zip",
                "size": 18429489,
                # Intentionally missing digest to test fallback to KNOWN_PINNED_HASHES
            },
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    assets = fetch_release_assets_metadata(tag="b10930", session=mock_session)
    assert len(assets) == 2

    vulkan_asset = assets["llama-b10930-bin-win-vulkan-x64.zip"]
    assert vulkan_asset.size == 31675441
    assert "ee489d90" in (vulkan_asset.digest or "")

    cpu_asset = assets["llama-b10930-bin-win-cpu-x64.zip"]
    # Fallback to known hash
    assert "a0c1bf04" in (cpu_asset.digest or "")


def test_fetch_release_assets_metadata_errors() -> None:
    """Verify HTTP errors raise RuntimeDownloadError."""
    mock_session = MagicMock(spec=requests.Session)

    # 404 Not Found
    resp_404 = MagicMock()
    resp_404.status_code = 404
    mock_session.get.return_value = resp_404
    with pytest.raises(RuntimeDownloadError, match="not found"):
        fetch_release_assets_metadata("nonexistent-tag", session=mock_session)

    # 403 Rate Limit
    resp_403 = MagicMock()
    resp_403.status_code = 403
    mock_session.get.return_value = resp_403
    with pytest.raises(RuntimeDownloadError, match="rate limit"):
        fetch_release_assets_metadata("b10930", session=mock_session)


# ==============================================================================
# Download & Integrity Verification Tests
# ==============================================================================

def test_download_and_verify_asset_success(tmp_path: Path) -> None:
    """Verify streaming download with matching SHA-256 succeeds."""
    content = b"Mock valid archive data 12345"
    digest = hashlib.sha256(content).hexdigest()

    asset = ReleaseAssetInfo(
        name="test-asset.zip",
        download_url="https://example.com/test-asset.zip",
        size=len(content),
        digest=f"sha256:{digest}",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(content))}
    mock_resp.iter_content.return_value = [content[:10], content[10:]]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    progress_events = []
    def on_progress(done: int, total: int) -> None:
        progress_events.append((done, total))

    out_file = download_and_verify_asset(
        asset=asset,
        dest_dir=tmp_path,
        session=mock_session,
        progress_callback=on_progress,
    )

    assert out_file.is_file()
    assert out_file.read_bytes() == content
    assert not (tmp_path / "test-asset.zip.part").exists()
    assert len(progress_events) == 2


def test_download_and_verify_asset_corrupted_payload_refuses_extraction(tmp_path: Path) -> None:
    """Corrupted download payload raises RuntimeIntegrityError and cleans up .part file."""
    real_content = b"Legitimate content"
    real_digest = hashlib.sha256(real_content).hexdigest()

    corrupted_content = b"Tampered or truncated content!"

    asset = ReleaseAssetInfo(
        name="corrupted-asset.zip",
        download_url="https://example.com/corrupted.zip",
        size=len(corrupted_content),
        digest=f"sha256:{real_digest}",  # Expects real digest, gets corrupted
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(corrupted_content))}
    mock_resp.iter_content.return_value = [corrupted_content]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    with pytest.raises(RuntimeIntegrityError, match="integrity verification FAILED"):
        download_and_verify_asset(asset=asset, dest_dir=tmp_path, session=mock_session)

    # Invariant: Neither final archive nor .part file should remain on disk
    assert not (tmp_path / "corrupted-asset.zip").exists()
    assert not (tmp_path / "corrupted-asset.zip.part").exists()


def test_download_and_verify_asset_github_digest_missing_hardcoded_present(tmp_path: Path) -> None:
    """If GitHub API digest is missing, verification succeeds using KNOWN_PINNED_HASHES alone."""
    content = b"Mock archive bytes with hardcoded hash only"
    digest = hashlib.sha256(content).hexdigest()

    asset = ReleaseAssetInfo(
        name="llama-b10930-bin-win-test-x64.zip",
        download_url="https://example.com/asset.zip",
        size=len(content),
        digest=None,  # GitHub API did not provide a digest!
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(content))}
    mock_resp.iter_content.return_value = [content]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    with patch.dict("core.runtime_manager.KNOWN_PINNED_HASHES", {asset.name: digest}):
        out_file = download_and_verify_asset(asset=asset, dest_dir=tmp_path, session=mock_session)
        assert out_file.is_file()
        assert out_file.read_bytes() == content


def test_download_and_verify_asset_both_missing_refuses(tmp_path: Path) -> None:
    """If BOTH GitHub API digest and hardcoded hash are missing, verification fails closed."""
    content = b"Untrusted archive bytes with no hash anywhere"

    asset = ReleaseAssetInfo(
        name="untrusted-unhashed-asset.zip",
        download_url="https://example.com/untrusted.zip",
        size=len(content),
        digest=None,  # Neither GitHub API...
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(content))}
    mock_resp.iter_content.return_value = [content]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    # Ensure asset.name is NOT in KNOWN_PINNED_HASHES
    with pytest.raises(RuntimeIntegrityError, match="Security violation: No authoritative SHA-256 digest available"):
        download_and_verify_asset(asset=asset, dest_dir=tmp_path, session=mock_session)

    # Invariant: Must fail closed - refuse to keep archive or partial file
    assert not (tmp_path / "untrusted-unhashed-asset.zip").exists()
    assert not (tmp_path / "untrusted-unhashed-asset.zip.part").exists()


def test_download_and_verify_asset_cross_verify_mismatch_refuses(tmp_path: Path) -> None:
    """If GitHub API digest and authoritative pinned hash contradict each other, refuse extraction."""
    content = b"Archive bytes"
    github_hash = "aaaa" * 16
    pinned_hash = "bbbb" * 16

    asset = ReleaseAssetInfo(
        name="mismatch-asset.zip",
        download_url="https://example.com/mismatch.zip",
        size=len(content),
        digest=f"sha256:{github_hash}",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(content))}
    mock_resp.iter_content.return_value = [content]
    mock_resp.__enter__.return_value = mock_resp

    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.return_value = mock_resp

    with patch.dict("core.runtime_manager.KNOWN_PINNED_HASHES", {asset.name: pinned_hash}):
        with pytest.raises(RuntimeIntegrityError, match="Digest mismatch between GitHub API digest"):
            download_and_verify_asset(asset=asset, dest_dir=tmp_path, session=mock_session)

    assert not (tmp_path / "mismatch-asset.zip").exists()
    assert not (tmp_path / "mismatch-asset.zip.part").exists()


# ==============================================================================
# Safe Extraction & Zip-Slip Protection Tests
# ==============================================================================

def test_safe_extract_zip_valid(tmp_path: Path) -> None:
    """Safe extraction unpacks clean members without error."""
    zip_bytes = _create_test_zip({
        "llama-server.exe": b"fake-exe",
        "nested/dependency.dll": b"fake-dll",
    })
    zip_path = tmp_path / "test.zip"
    zip_path.write_bytes(zip_bytes)

    dest_dir = tmp_path / "extracted"
    safe_extract_zip(zip_path, dest_dir)

    assert (dest_dir / "llama-server.exe").read_bytes() == b"fake-exe"
    assert (dest_dir / "nested" / "dependency.dll").read_bytes() == b"fake-dll"


def test_safe_extract_zip_slip_rejection(tmp_path: Path) -> None:
    """Zip-slip malicious member path raises ZipSlipSecurityError and extracts nothing."""
    dest_dir = tmp_path / "safe_dir"
    dest_dir.mkdir()

    # Craft an archive with directory traversal member
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../evil_payload.exe", b"malicious data")

    with pytest.raises(ZipSlipSecurityError, match="Zip-slip path traversal"):
        safe_extract_zip(zip_path, dest_dir)

    # Invariant: Escaped target file must NOT be written
    assert not (tmp_path / "evil_payload.exe").exists()


# ==============================================================================
# Post-Install Binary Validation Tests
# ==============================================================================

def test_validate_runtime_binary(tmp_path: Path) -> None:
    """Verify validation check executes minimal invocation."""
    exe = tmp_path / "fake-server.exe"
    exe.write_bytes(b"MZ...")

    # Success case: returns 0
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert validate_runtime_binary(exe) is True
        expected_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        mock_run.assert_called_with(
            [str(exe), "--version"],
            stdout=-1,
            stderr=-1,
            timeout=5.0,
            creationflags=expected_flags,
        )

    # Failure case: returns non-zero on both --version and -h
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert validate_runtime_binary(exe) is False

    # Missing file
    assert validate_runtime_binary(tmp_path / "missing.exe") is False


def test_validate_runtime_binary_timeout_hang(tmp_path: Path) -> None:
    """Verify that a hanging binary triggers the 5s timeout, aborts cleanly, and returns False."""
    exe = tmp_path / "hanging-server.exe"
    exe.write_bytes(b"MZ...")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[str(exe), "--version"], timeout=5.0)) as mock_run:
        assert validate_runtime_binary(exe) is False
        # Invariant: On timeout, must abort immediately without trying second flag (-h)
        assert mock_run.call_count == 1


def test_validate_runtime_binary_restores_error_mode(tmp_path: Path) -> None:
    """Verify validate_runtime_binary restores original Win32 error mode on success, failure, and timeout."""
    exe = tmp_path / "test-server.exe"
    exe.write_bytes(b"MZ...")

    if sys.platform == "win32":
        import ctypes
        initial_mode = ctypes.windll.kernel32.GetErrorMode()

        # 1. Success path
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            res = validate_runtime_binary(exe)
            assert res is True
            assert ctypes.windll.kernel32.GetErrorMode() == initial_mode

        # 2. Failure path (non-zero return code)
        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            res = validate_runtime_binary(exe)
            assert res is False
            assert ctypes.windll.kernel32.GetErrorMode() == initial_mode

        # 3. Timeout / Hang path
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[str(exe), "--version"], timeout=5.0)):
            res = validate_runtime_binary(exe)
            assert res is False
            assert ctypes.windll.kernel32.GetErrorMode() == initial_mode

        # 4. Unexpected exception path
        with patch("subprocess.run", side_effect=OSError("Process spawn failure")):
            res = validate_runtime_binary(exe)
            assert res is False
            assert ctypes.windll.kernel32.GetErrorMode() == initial_mode
    else:
        # Cross-platform mock test for non-Windows environments
        mock_kernel32 = MagicMock()
        mock_kernel32.GetErrorMode.return_value = 0x8001
        with (
            patch("sys.platform", "win32"),
            patch("ctypes.windll.kernel32", mock_kernel32, create=True),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[str(exe), "--version"], timeout=5.0)),
        ):
            res = validate_runtime_binary(exe)
            assert res is False
            mock_kernel32.SetErrorMode.assert_called_with(0x8001)


# ==============================================================================
# Idempotency & Cache Verification Tests
# ==============================================================================

def test_is_runtime_installed_and_path(tmp_path: Path) -> None:
    """Verify detection of cached installed runtimes."""
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        target_dir = tmp_path / "b10930-cuda"
        target_dir.mkdir(parents=True)

        exe_name = "llama-server.exe" if pytest.importorskip("sys").platform == "win32" else "llama-server"
        exe = target_dir / exe_name
        exe.write_bytes(b"bin")

        manifest = target_dir / "manifest.json"
        manifest.write_text(json.dumps({"tag": "b10930", "backend": "cuda"}), encoding="utf-8")

        assert is_runtime_installed("b10930", "cuda") is True
        installed_path = get_installed_runtime_path("b10930", "cuda")
        assert installed_path == exe

        # Different backend or missing manifest returns False
        assert is_runtime_installed("b10930", "vulkan") is False
        assert get_installed_runtime_path("b10930", "vulkan") is None


# ==============================================================================
# End-to-End Orchestration & Failure Recovery Tests
# ==============================================================================

def test_ensure_runtime_end_to_end_mocked(tmp_path: Path) -> None:
    """Verify complete download, verification, extraction, and manifest creation flow."""
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        exe_name = "llama-server.exe" if pytest.importorskip("sys").platform == "win32" else "llama-server"
        zip_bytes = _create_test_zip({exe_name: b"mock binary", "lib.dll": b"lib"})
        zip_digest = hashlib.sha256(zip_bytes).hexdigest()

        mock_meta = {
            f"llama-b10930-bin-win-cpu-x64.zip": ReleaseAssetInfo(
                name="llama-b10930-bin-win-cpu-x64.zip",
                download_url="https://mock/cpu.zip",
                size=len(zip_bytes),
                digest=f"sha256:{zip_digest}",
            )
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": str(len(zip_bytes))}
        mock_resp.iter_content.return_value = [zip_bytes]
        mock_resp.__enter__.return_value = mock_resp

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_resp

        with (
            patch("core.runtime_manager.fetch_release_assets_metadata", return_value=mock_meta),
            patch("core.runtime_manager.validate_runtime_binary", return_value=True),
            patch.dict("core.runtime_manager.KNOWN_PINNED_HASHES", {"llama-b10930-bin-win-cpu-x64.zip": zip_digest}),
        ):
            final_exe = ensure_runtime(backend="cpu", tag="b10930", session=mock_session)

            assert final_exe.is_file()
            assert final_exe.name == exe_name
            runtime_dir = get_runtime_dir("b10930", "cpu")
            assert (runtime_dir / "manifest.json").is_file()

            # Calling a second time without force must hit cache and do zero network calls
            mock_session.get.reset_mock()
            cached_exe = ensure_runtime(backend="cpu", tag="b10930", session=mock_session)
            assert cached_exe == final_exe
            mock_session.get.assert_not_called()

            # Calling a third time with force=True MUST bypass cache and re-download
            mock_session.get.reset_mock()
            forced_exe = ensure_runtime(backend="cpu", tag="b10930", session=mock_session, force=True)
            assert forced_exe == final_exe
            mock_session.get.assert_called_once()


def test_ensure_runtime_force_reinstall_bypasses_cache(tmp_path: Path) -> None:
    """Verify force=True triggers a complete re-download and overwrites existing installation."""
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        exe_name = "llama-server.exe" if pytest.importorskip("sys").platform == "win32" else "llama-server"
        zip_bytes = _create_test_zip({exe_name: b"binary v2", "version.txt": b"2.0"})
        zip_digest = hashlib.sha256(zip_bytes).hexdigest()

        # Seed an existing installation
        runtime_dir = get_runtime_dir("b10930", "cpu")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / exe_name).write_bytes(b"binary v1")
        (runtime_dir / "manifest.json").write_text(json.dumps({"tag": "b10930", "backend": "cpu"}), encoding="utf-8")

        mock_meta = {
            "llama-b10930-bin-win-cpu-x64.zip": ReleaseAssetInfo(
                name="llama-b10930-bin-win-cpu-x64.zip",
                download_url="https://mock/cpu.zip",
                size=len(zip_bytes),
                digest=f"sha256:{zip_digest}",
            )
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": str(len(zip_bytes))}
        mock_resp.iter_content.return_value = [zip_bytes]
        mock_resp.__enter__.return_value = mock_resp

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_resp

        with (
            patch("core.runtime_manager.fetch_release_assets_metadata", return_value=mock_meta),
            patch("core.runtime_manager.validate_runtime_binary", return_value=True),
            patch.dict("core.runtime_manager.KNOWN_PINNED_HASHES", {"llama-b10930-bin-win-cpu-x64.zip": zip_digest}),
        ):
            # force=False returns existing without network calls
            p_cached = ensure_runtime(backend="cpu", tag="b10930", session=mock_session, force=False)
            assert p_cached.read_bytes() == b"binary v1"
            mock_session.get.assert_not_called()

            # force=True re-downloads and updates binary to v2
            p_forced = ensure_runtime(backend="cpu", tag="b10930", session=mock_session, force=True)
            assert p_forced.read_bytes() == b"binary v2"
            mock_session.get.assert_called_once()
            assert (runtime_dir / "version.txt").read_bytes() == b"2.0"


def test_ensure_runtime_cleanup_on_validation_failure(tmp_path: Path) -> None:
    """Verify that if binary validation fails, staging directory is wiped and error is raised."""
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        exe_name = "llama-server.exe" if pytest.importorskip("sys").platform == "win32" else "llama-server"
        zip_bytes = _create_test_zip({exe_name: b"crashed binary"})
        zip_digest = hashlib.sha256(zip_bytes).hexdigest()

        mock_meta = {
            f"llama-b10930-bin-win-cpu-x64.zip": ReleaseAssetInfo(
                name="llama-b10930-bin-win-cpu-x64.zip",
                download_url="https://mock/cpu.zip",
                size=len(zip_bytes),
                digest=f"sha256:{zip_digest}",
            )
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": str(len(zip_bytes))}
        mock_resp.iter_content.return_value = [zip_bytes]
        mock_resp.__enter__.return_value = mock_resp

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_resp

        with (
            patch("core.runtime_manager.fetch_release_assets_metadata", return_value=mock_meta),
            patch("core.runtime_manager.validate_runtime_binary", return_value=False),  # Validation fails!
            patch.dict("core.runtime_manager.KNOWN_PINNED_HASHES", {"llama-b10930-bin-win-cpu-x64.zip": zip_digest}),
        ):
            with pytest.raises(RuntimeValidationError, match="failed to execute"):
                ensure_runtime(backend="cpu", tag="b10930", session=mock_session)

            # Invariant: final runtime directory must NOT have been created
            assert not get_runtime_dir("b10930", "cpu").exists()
            # Staging directories must be wiped
            staging_dirs = list(tmp_path.glob("staging_*"))
            assert len(staging_dirs) == 0


def test_ensure_runtime_cuda_cudart_failure_discards_staging(tmp_path: Path) -> None:
    """Multi-archive CUDA staging: if companion cudart download fails after primary succeeds,
    staging is completely wiped, manifest.json is never written, and install is invalid.
    """
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        exe_name = "llama-server.exe" if pytest.importorskip("sys").platform == "win32" else "llama-server"
        primary_zip = _create_test_zip({exe_name: b"primary binary"})
        primary_digest = hashlib.sha256(primary_zip).hexdigest()

        primary_name = "llama-b10930-bin-win-cuda-12.4-x64.zip"
        cudart_name = "cudart-llama-bin-win-cuda-12.4-x64.zip"

        mock_meta = {
            primary_name: ReleaseAssetInfo(
                name=primary_name,
                download_url="https://mock/primary.zip",
                size=len(primary_zip),
                digest=f"sha256:{primary_digest}",
            ),
            cudart_name: ReleaseAssetInfo(
                name=cudart_name,
                download_url="https://mock/cudart.zip",
                size=12345,
                digest="sha256:1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            ),
        }

        # Mock download_and_verify_asset: primary succeeds, cudart fails
        def mock_download_and_verify(asset, dest_dir, session=None, progress_callback=None):
            if asset.name == primary_name:
                dest_file = dest_dir / primary_name
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                dest_file.write_bytes(primary_zip)
                return dest_file
            raise RuntimeDownloadError("Network error: CUDART download interrupted")

        mock_session = MagicMock(spec=requests.Session)

        with (
            patch("core.runtime_manager.fetch_release_assets_metadata", return_value=mock_meta),
            patch("core.runtime_manager.download_and_verify_asset", side_effect=mock_download_and_verify),
            patch.dict("core.runtime_manager.KNOWN_PINNED_HASHES", {primary_name: primary_digest}),
        ):
            with pytest.raises(RuntimeDownloadError, match="CUDART download interrupted"):
                ensure_runtime(backend="cuda", tag="b10930", session=mock_session)

            # Invariant: final runtime directory must NOT exist
            assert not get_runtime_dir("b10930", "cuda").exists()
            assert is_runtime_installed("b10930", "cuda") is False
            assert get_installed_runtime_path("b10930", "cuda") is None

            # Invariant: manifest.json was never written
            manifest_files = list(tmp_path.glob("**/manifest.json"))
            assert len(manifest_files) == 0

            # Invariant: all staging_* folders must be wiped
            staging_dirs = list(tmp_path.glob("staging_*"))
            assert len(staging_dirs) == 0
