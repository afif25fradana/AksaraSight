"""Tests for core.model_manager and server_manager model path integration."""

import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from core.model_manager import (
    PINNED_MODEL_FILES,
    PINNED_MODEL_REPO,
    TOTAL_MODEL_BYTES,
    ModelDownloader,
    get_local_model_paths,
    get_models_dir,
)
from core.server_manager import ServerManager, ServerStatus


def test_get_local_model_paths_detects_existing(tmp_path):
    """Test 1: get_local_model_paths detects local files when valid and respects verification."""
    fake_model = tmp_path / "GLM-OCR-Q8_0.gguf"
    fake_model_content = b"model-weights-content-sample"
    fake_model.write_bytes(fake_model_content)

    fake_mmproj = tmp_path / "mmproj-GLM-OCR-Q8_0.gguf"
    fake_mmproj_content = b"mmproj-weights-content-sample"
    fake_mmproj.write_bytes(fake_mmproj_content)

    mock_files_spec = {
        "model": {
            "filename": "GLM-OCR-Q8_0.gguf",
            "sha256": hashlib.sha256(fake_model_content).hexdigest(),
            "size_bytes": len(fake_model_content),
        },
        "mmproj": {
            "filename": "mmproj-GLM-OCR-Q8_0.gguf",
            "sha256": hashlib.sha256(fake_mmproj_content).hexdigest(),
            "size_bytes": len(fake_mmproj_content),
        },
    }

    with patch("core.model_manager.get_models_dir", return_value=tmp_path):
        with patch.dict("core.model_manager.PINNED_MODEL_FILES", mock_files_spec):
            # Fast size-based detection
            detected = get_local_model_paths()
            assert detected is not None
            assert detected == (fake_model, fake_mmproj)

            # Full SHA-256 verification
            verified = get_local_model_paths(verify_hash=True)
            assert verified == (fake_model, fake_mmproj)

            # Passing non-pinned repo falls back to None
            assert get_local_model_paths(repo="unrelated/other-model") is None

            # Size mismatch returns None
            corrupt_spec = dict(mock_files_spec)
            corrupt_spec["model"] = dict(mock_files_spec["model"])
            corrupt_spec["model"]["size_bytes"] = 9999999
            with patch.dict("core.model_manager.PINNED_MODEL_FILES", corrupt_spec):
                assert get_local_model_paths() is None


def test_downloader_disk_space_check_fails_on_full_disk(tmp_path):
    """Test 2: ModelDownloader pre-flight fails when disk free space is below threshold."""
    mock_usage = MagicMock()
    mock_usage.free = 100  # Only 100 bytes free
    mock_usage.total = 10_000_000_000
    mock_usage.used = 9_999_999_900

    downloader = ModelDownloader(dest_dir=tmp_path)
    with patch("shutil.disk_usage", return_value=mock_usage):
        with pytest.raises(OSError, match="Insufficient disk space"):
            downloader.download()

    assert downloader.is_downloading is False
    assert downloader.error_message is not None
    assert "Insufficient disk space" in downloader.error_message


def test_downloader_sha256_mismatch_fails_closed(tmp_path):
    """Test 3: Corrupt download stream fails SHA-256 check and deletes corrupt partial file."""
    mock_usage = MagicMock()
    mock_usage.free = 50_000_000_000

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [b"corrupt-payload-data"]
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp

    downloader = ModelDownloader(dest_dir=tmp_path, session=mock_session)

    with patch("shutil.disk_usage", return_value=mock_usage):
        with pytest.raises(ValueError, match="Digest mismatch"):
            downloader.download()

    # Fail-closed guarantee: verify no .part files and no target files remain
    part_files = list(tmp_path.glob("*.part"))
    gguf_files = list(tmp_path.glob("*.gguf"))
    assert len(part_files) == 0
    assert len(gguf_files) == 0
    assert downloader.is_downloading is False
    assert downloader.error_message is not None
    assert "Digest mismatch" in downloader.error_message


def test_downloader_resume_sends_range_header(tmp_path):
    """Test 4: When .part file exists, downloader sends Range: bytes=<size>- header."""
    filename = PINNED_MODEL_FILES["model"]["filename"]
    part_file = tmp_path / f"{filename}.part"
    part_file.write_bytes(b"A" * 4096)

    mock_usage = MagicMock()
    mock_usage.free = 50_000_000_000

    captured_headers = {}

    def mock_get(url, headers=None, **kwargs):
        if headers:
            captured_headers.update(headers)
        mock_resp = MagicMock()
        mock_resp.status_code = 206
        mock_resp.iter_content.return_value = [b"B" * 512]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        # Cancel while downloading to inspect partial state
        downloader.cancel()
        return mock_resp

    mock_session = MagicMock()
    mock_session.get.side_effect = mock_get

    downloader = ModelDownloader(dest_dir=tmp_path, session=mock_session)

    with patch("shutil.disk_usage", return_value=mock_usage):
        res = downloader.download()
        assert res is False  # Stopped due to cancel

    assert "Range" in captured_headers
    assert captured_headers["Range"] == "bytes=4096-"
    assert part_file.exists()  # Preserved on cancel for resumption


def test_server_manager_falls_back_to_hf_when_no_local_model(tmp_path):
    """Test 5: server_manager uses -hf when get_local_model_paths returns None."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")

    settings = Settings(
        llama_server_path=str(fake_exe),
        runtime_mode="custom",
        model_repo=PINNED_MODEL_REPO,
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter(["[server] listening on 127.0.0.1:8080\n"])

    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("core.server_manager.get_local_model_paths", return_value=None):
                with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                    mgr.start()
                    assert mock_popen.called
                    cmd_args = mock_popen.call_args[0][0]
                    assert "-hf" in cmd_args
                    assert PINNED_MODEL_REPO in cmd_args
                    assert "-m" not in cmd_args
    finally:
        mgr.shutdown()


def test_server_manager_uses_m_when_local_model_present(tmp_path):
    """Test 6: server_manager uses -m and --mmproj when get_local_model_paths returns valid paths."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")

    fake_model = tmp_path / "GLM-OCR-Q8_0.gguf"
    fake_mmproj = tmp_path / "mmproj-GLM-OCR-Q8_0.gguf"

    settings = Settings(
        llama_server_path=str(fake_exe),
        runtime_mode="custom",
        model_repo=PINNED_MODEL_REPO,
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter(["[server] listening on 127.0.0.1:8080\n"])

    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("core.server_manager.get_local_model_paths", return_value=(fake_model, fake_mmproj)):
                with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                    mgr.start()
                    assert mock_popen.called
                    cmd_args = mock_popen.call_args[0][0]
                    assert "-m" in cmd_args
                    assert str(fake_model) in cmd_args
                    assert "--mmproj" in cmd_args
                    assert str(fake_mmproj) in cmd_args
                    assert "-hf" not in cmd_args
    finally:
        mgr.shutdown()


def test_downloader_prevents_concurrent_downloads(tmp_path):
    """Verify concurrent download calls raise RuntimeError."""
    mock_usage = MagicMock()
    mock_usage.free = 50_000_000_000

    d1 = ModelDownloader(dest_dir=tmp_path)
    d2 = ModelDownloader(dest_dir=tmp_path)

    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False

    with patch("shutil.disk_usage", return_value=mock_usage):
        with patch.object(d1, "_execute_download", return_value=True):
            with patch("core.model_manager._ACTIVE_DOWNLOAD_LOCK", mock_lock):
                with pytest.raises(RuntimeError, match="Download already in progress"):
                    d2.download()


def test_downloader_progress_callback(tmp_path):
    """Verify progress callback is invoked with expected status schema."""
    updates = []

    def callback(status):
        updates.append(dict(status))

    downloader = ModelDownloader(dest_dir=tmp_path, progress_callback=callback)
    downloader._notify_progress()

    assert len(updates) == 1
    assert "is_downloading" in updates[0]
    assert "bytes_downloaded" in updates[0]
    assert "total_bytes" in updates[0]
    assert "percent" in updates[0]
    assert updates[0]["total_bytes"] == TOTAL_MODEL_BYTES
