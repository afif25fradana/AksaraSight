"""Tests for core.model_manager and server_manager model path integration."""

import hashlib
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


def test_server_manager_does_not_hijack_custom_repo(tmp_path):
    """Verify ServerManager does not hijack custom model repo or custom model file."""
    fake_exe = tmp_path / "llama-server.exe"
    fake_exe.write_text("binary", encoding="utf-8")

    fake_model = tmp_path / "GLM-OCR-Q8_0.gguf"
    fake_mmproj = tmp_path / "mmproj-GLM-OCR-Q8_0.gguf"
    fake_model_content = b"model-weights-sample"
    fake_mmproj_content = b"mmproj-weights-sample"
    fake_model.write_bytes(fake_model_content)
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

    # 1. Custom HF repo containing 'glm-ocr' in its name
    custom_repo = "other-org/custom-glm-ocr-finetune"
    settings = Settings(
        llama_server_path=str(fake_exe),
        runtime_mode="custom",
        model_repo=custom_repo,
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr = ServerManager(settings=settings)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdout = iter(["[server] listening on 127.0.0.1:8080\n"])

    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("core.model_manager.get_models_dir", return_value=tmp_path):
                with patch.dict("core.model_manager.PINNED_MODEL_FILES", mock_files_spec):
                    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                        mgr.start()
                        assert mock_popen.called
                        cmd_args = mock_popen.call_args[0][0]
                        assert "-hf" in cmd_args
                        assert custom_repo in cmd_args
                        assert "-m" not in cmd_args
    finally:
        mgr.shutdown()

    # 2. Custom local .gguf file uses -m flag with user's model file
    custom_model_file = tmp_path / "custom-model.gguf"
    custom_model_file.write_bytes(b"custom-weights")

    settings_custom_m = Settings(
        llama_server_path=str(fake_exe),
        runtime_mode="custom",
        model_repo=str(custom_model_file),
        local_endpoint="http://127.0.0.1:8080/v1",
    )
    mgr_custom_m = ServerManager(settings=settings_custom_m)
    try:
        with patch("core.server_manager.probe_server_health", return_value=(ServerStatus.OFFLINE, "Offline")):
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                mgr_custom_m.start()
                assert mock_popen.called
                cmd_args = mock_popen.call_args[0][0]
                assert "-m" in cmd_args
                assert str(custom_model_file) in cmd_args
                assert "-hf" not in cmd_args
    finally:
        mgr_custom_m.shutdown()


def test_downloader_incomplete_dest_file_cleaned_up(tmp_path):
    """Verify that an incomplete or invalid dest_file is deleted upon download initiation."""
    filename = PINNED_MODEL_FILES["model"]["filename"]
    dest_file = tmp_path / filename
    # Write an incomplete file whose size doesn't match expected_size
    dest_file.write_bytes(b"short-invalid-data")
    assert dest_file.exists()

    mock_usage = MagicMock()
    mock_usage.free = 50_000_000_000

    def mock_get(url, **kwargs):
        # By the time download begins streaming, dest_file should have already been unlinked
        assert not dest_file.exists()
        downloader.cancel()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = []
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        return mock_resp

    mock_session = MagicMock()
    mock_session.get.side_effect = mock_get

    downloader = ModelDownloader(dest_dir=tmp_path, session=mock_session)

    with patch("shutil.disk_usage", return_value=mock_usage):
        downloader.download()

    assert not dest_file.exists()


def test_downloader_resumed_part_file_sha256_mismatch_deleted(tmp_path):
    """Verify resumed .part file with HTTP 206 is deleted when SHA-256 digest mismatches."""
    filename = PINNED_MODEL_FILES["model"]["filename"]
    part_file = tmp_path / f"{filename}.part"
    part_file.write_bytes(b"initial-corrupt-prefix-")
    existing_len = part_file.stat().st_size

    mock_usage = MagicMock()
    mock_usage.free = 50_000_000_000

    captured_headers = {}

    def mock_get(url, headers=None, **kwargs):
        if headers:
            captured_headers.update(headers)
        mock_resp = MagicMock()
        mock_resp.status_code = 206
        mock_resp.iter_content.return_value = [b"resumed-stream-suffix"]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None
        return mock_resp

    mock_session = MagicMock()
    mock_session.get.side_effect = mock_get

    downloader = ModelDownloader(dest_dir=tmp_path, session=mock_session)

    with patch("shutil.disk_usage", return_value=mock_usage):
        with pytest.raises(ValueError, match="Digest mismatch"):
            downloader.download()

    assert captured_headers.get("Range") == f"bytes={existing_len}-"
    assert not part_file.exists()
    assert downloader.is_downloading is False
    assert downloader.error_message is not None
    assert "Digest mismatch" in downloader.error_message


def test_downloader_notifies_sha256_verification(tmp_path):
    """Verify ModelDownloader notifies progress with 'Verifying ... (SHA-256)...' when checking existing files."""
    fake_model_content = b"fake-model-bytes"
    fake_mmproj_content = b"fake-mmproj-bytes"

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

    model_file = tmp_path / "GLM-OCR-Q8_0.gguf"
    model_file.write_bytes(fake_model_content)

    part_file = tmp_path / "mmproj-GLM-OCR-Q8_0.gguf.part"
    part_file.write_bytes(fake_mmproj_content)

    mock_usage = MagicMock()
    mock_usage.free = 50_000_000_000

    observed_files = []

    def progress_callback(status):
        observed_files.append(status.get("current_file"))

    downloader = ModelDownloader(dest_dir=tmp_path, progress_callback=progress_callback)

    with patch.dict("core.model_manager.PINNED_MODEL_FILES", mock_files_spec):
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = downloader.download()
            assert res is True

    assert "Verifying GLM-OCR-Q8_0.gguf (SHA-256)..." in observed_files
    assert "Verifying mmproj-GLM-OCR-Q8_0.gguf.part (SHA-256)..." in observed_files


def test_model_downloader_default_session_has_trust_env_false() -> None:
    """Verify ModelDownloader creates an isolated Session with trust_env=False when none provided."""
    downloader = ModelDownloader()
    assert downloader.session is not None
    assert downloader.session.trust_env is False


def test_model_downloader_resets_is_downloading_on_disk_error(tmp_path: Path) -> None:
    """Verify that an unexpected disk I/O error outside the streaming block resets is_downloading to False."""
    downloader = ModelDownloader(dest_dir=tmp_path / "models")
    
    # Simulate a PermissionError (e.g. Windows WinError 32) when unlinking/verifying destination file
    with patch("core.model_manager._compute_sha256", side_effect=PermissionError(32, "File in use")):
        # Create dummy file so _compute_sha256 gets called
        spec = PINNED_MODEL_FILES["model"]
        dest_file = downloader.dest_dir / spec["filename"]
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_bytes(b"0" * spec["size_bytes"])
        
        with pytest.raises(PermissionError):
            downloader.download()
            
        # In bug condition, is_downloading stays True permanently!
        # In fixed condition, is_downloading must be False.
        assert downloader.is_downloading is False
        assert downloader.error_message is not None


def test_get_models_dir_linux_xdg_parity(monkeypatch, tmp_path: Path) -> None:
    """Linux models directory adheres to XDG Base Directory specification and lowercase aksarasight."""
    monkeypatch.setattr("sys.platform", "linux")
    from core.model_manager import get_models_dir

    # Case 1: Custom XDG_DATA_HOME
    custom_xdg = tmp_path / "custom_data"
    monkeypatch.setenv("XDG_DATA_HOME", str(custom_xdg))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    resolved = get_models_dir()
    expected_custom = custom_xdg / "aksarasight" / "models" / "glm-ocr-q8_0"
    assert resolved == expected_custom
    assert "AksaraSight" not in resolved.parts
    assert "aksarasight" in resolved.parts

    # Case 2: Default XDG location (~/.local/share/aksarasight/models/glm-ocr-q8_0)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    fake_home = tmp_path / "user_home"
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    resolved_default = get_models_dir()
    expected_default = fake_home / ".local" / "share" / "aksarasight" / "models" / "glm-ocr-q8_0"
    assert resolved_default == expected_default
    assert "AksaraSight" not in resolved_default.parts
    assert "aksarasight" in resolved_default.parts


def test_models_dir_linux_legacy_migration_fallback(monkeypatch, tmp_path: Path) -> None:
    """Legacy ~/.local/share/AksaraSight/models with weights migrates or falls back to canonical lowercase path."""
    from core.model_manager import get_models_dir

    monkeypatch.setattr("sys.platform", "linux")
    fake_home = tmp_path / "user_home"
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    xdg_data = tmp_path / "xdg_data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    legacy_dir = fake_home / ".local" / "share" / "AksaraSight" / "models" / "glm-ocr-q8_0"
    legacy_dir.mkdir(parents=True)
    fake_model = legacy_dir / "GLM-OCR-Q8_0.gguf"
    fake_mmproj = legacy_dir / "mmproj-GLM-OCR-Q8_0.gguf"
    fake_model.write_bytes(b"legacy-model-weights")
    fake_mmproj.write_bytes(b"legacy-mmproj-weights")

    resolved = get_models_dir()
    assert "AksaraSight" not in resolved.parts
    assert "aksarasight" in resolved.parts
    assert (resolved / "GLM-OCR-Q8_0.gguf").read_bytes() == b"legacy-model-weights"
    assert (resolved / "mmproj-GLM-OCR-Q8_0.gguf").read_bytes() == b"legacy-mmproj-weights"
    assert not fake_model.exists()
    assert not fake_mmproj.exists()
    assert not (fake_home / ".local" / "share" / "AksaraSight").exists()


def test_migrate_legacy_models_samefile_guard(tmp_path: Path) -> None:
    """Verify _migrate_legacy_models returns False when legacy_dir and canonical_dir refer to the same directory."""
    from core.model_manager import _migrate_legacy_models

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True)
    dummy_file = models_dir / "dummy.txt"
    dummy_file.write_text("content", encoding="utf-8")

    result = _migrate_legacy_models(legacy_dir=models_dir, canonical_dir=models_dir)
    assert result is False
    assert dummy_file.exists()



