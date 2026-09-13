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
        ):
            final_exe = ensure_runtime(backend="cpu", tag="b10930", session=mock_session)

            assert final_exe.is_file()
            assert final_exe.name == exe_name
            runtime_dir = get_runtime_dir("b10930", "cpu")
            assert (runtime_dir / "manifest.json").is_file()

            # Calling a second time must hit cache and do zero network calls
            mock_session.get.reset_mock()
            cached_exe = ensure_runtime(backend="cpu", tag="b10930", session=mock_session)
            assert cached_exe == final_exe
            mock_session.get.assert_not_called()


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
        ):
            with pytest.raises(RuntimeValidationError, match="failed to execute"):
                ensure_runtime(backend="cpu", tag="b10930", session=mock_session)

            # Invariant: final runtime directory must NOT have been created
            assert not get_runtime_dir("b10930", "cpu").exists()
            # Staging directories must be wiped
            staging_dirs = list(tmp_path.glob("staging_*"))
            assert len(staging_dirs) == 0
