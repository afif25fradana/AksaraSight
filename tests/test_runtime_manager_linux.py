"""Linux-specific unit and functional tests for the runtime manager subsystem."""

import hashlib
import io
import os
from pathlib import Path
import stat
import sys
import tarfile
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.runtime_manager import (
    KNOWN_PINNED_HASHES,
    ReleaseAssetInfo,
    ZipSlipSecurityError,
    ensure_runtime,
    get_installed_runtime_path,
    get_runtime_base_dir,
    get_runtime_dir,
    is_runtime_installed,
    resolve_asset_names,
    resolve_effective_server_path,
    resolve_required_asset_names,
    safe_extract_archive,
    safe_extract_tar,
    validate_runtime_binary,
)


def _create_test_tar(
    files: dict[str, bytes],
    symlinks: Optional[dict[str, str]] = None,
    executable_files: Optional[set[str]] = None,
) -> bytes:
    """Helper to create an in-memory tar.gz archive."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data)
            ti.type = tarfile.REGTYPE
            if executable_files and name in executable_files:
                ti.mode = 0o755
            else:
                ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))
        if symlinks:
            for name, target in symlinks.items():
                ti = tarfile.TarInfo(name=name)
                ti.type = tarfile.SYMTYPE
                ti.linkname = target
                tf.addfile(ti)
    return buf.getvalue()


def test_resolve_required_asset_names_linux_vulkan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux vulkan backend resolves to Ubuntu Vulkan tar.gz archive."""
    monkeypatch.setattr("sys.platform", "linux")
    assets = resolve_required_asset_names("vulkan", "b11361")
    assert assets == ["llama-b11361-bin-ubuntu-vulkan-x64.tar.gz"]


def test_resolve_required_asset_names_linux_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux cpu backend resolves to Ubuntu CPU tar.gz archive."""
    monkeypatch.setattr("sys.platform", "linux")
    assets = resolve_required_asset_names("cpu", "b11361")
    assert assets == ["llama-b11361-bin-ubuntu-x64.tar.gz"]


def test_resolve_required_asset_names_linux_cuda_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Managed CUDA runtime is not supported on Linux and must raise ValueError."""
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(ValueError, match=r"(?i)cuda.*not supported on linux"):
        resolve_required_asset_names("cuda", "b11361")


def test_known_pinned_hashes_contains_linux_assets() -> None:
    """Verify KNOWN_PINNED_HASHES contains official SHA-256 digests for Linux b11361 assets."""
    assert "llama-b11361-bin-ubuntu-x64.tar.gz" in KNOWN_PINNED_HASHES
    assert (
        KNOWN_PINNED_HASHES["llama-b11361-bin-ubuntu-x64.tar.gz"]
        == "1b22cc0a6de07ff2f8a5b8cdebc75ba9cf157bab872b99f56e3ba15de6f2c469"
    )
    assert "llama-b11361-bin-ubuntu-vulkan-x64.tar.gz" in KNOWN_PINNED_HASHES
    assert (
        KNOWN_PINNED_HASHES["llama-b11361-bin-ubuntu-vulkan-x64.tar.gz"]
        == "0d2ef1ccef53e878d94e921eee4b0554ffc58452d1a9c628f3c221cb48c15eff"
    )


def test_safe_extract_tar_unnests_and_sets_mode(tmp_path: Path) -> None:
    """Safe tar extraction unpacks archive, un-nests top-level wrapper, and sets executable permissions."""
    tar_bytes = _create_test_tar(
        files={
            "llama-b11361/llama-server": b"fake-server-binary",
            "llama-b11361/libllama.so": b"fake-shared-lib",
        },
        symlinks={
            "llama-b11361/libllama.so.0": "libllama.so",
        },
        executable_files={"llama-b11361/llama-server"},
    )
    tar_path = tmp_path / "runtime.tar.gz"
    tar_path.write_bytes(tar_bytes)

    dest_dir = tmp_path / "extracted"
    safe_extract_tar(tar_path, dest_dir)

    server_bin = dest_dir / "llama-server"
    assert server_bin.is_file()
    assert server_bin.read_bytes() == b"fake-server-binary"
    if sys.platform != "win32":
        assert bool(server_bin.stat().st_mode & stat.S_IXUSR)

    lib_so = dest_dir / "libllama.so"
    assert lib_so.is_file()
    assert lib_so.read_bytes() == b"fake-shared-lib"

    symlink_file = dest_dir / "libllama.so.0"
    if sys.platform != "win32":
        assert symlink_file.is_symlink()
        assert os.readlink(symlink_file) == "libllama.so"
    else:
        assert symlink_file.exists()
        if symlink_file.is_symlink():
            assert os.readlink(symlink_file) == "libllama.so"


def test_safe_extract_tar_tarslip_rejected(tmp_path: Path) -> None:
    """Tar-slip path traversal member raises ZipSlipSecurityError and extracts nothing."""
    dest_dir = tmp_path / "safe_dir"
    dest_dir.mkdir()

    tar_bytes = _create_test_tar(files={"../../evil.sh": b"echo evil"})
    tar_path = tmp_path / "evil.tar.gz"
    tar_path.write_bytes(tar_bytes)

    with pytest.raises(ZipSlipSecurityError, match=r"(?i)tar-slip|zip-slip|path traversal"):
        safe_extract_tar(tar_path, dest_dir)

    assert not (tmp_path / "evil.sh").exists()


def test_safe_extract_tar_escaping_symlink_rejected(tmp_path: Path) -> None:
    """Tar member symlink escaping target destination raises ZipSlipSecurityError."""
    dest_dir = tmp_path / "safe_dir"
    dest_dir.mkdir()

    # Relative traversal symlink
    tar_bytes_rel = _create_test_tar(
        files={"regular.txt": b"ok"},
        symlinks={"evil_link": "../../outside"},
    )
    tar_path_rel = tmp_path / "evil_rel.tar.gz"
    tar_path_rel.write_bytes(tar_bytes_rel)

    with pytest.raises(ZipSlipSecurityError, match=r"(?i)symlink|path traversal|escaping|tar-slip|zip-slip"):
        safe_extract_tar(tar_path_rel, dest_dir)

    # Absolute traversal symlink
    tar_bytes_abs = _create_test_tar(
        files={"regular.txt": b"ok"},
        symlinks={"evil_abs": "/etc/passwd"},
    )
    tar_path_abs = tmp_path / "evil_abs.tar.gz"
    tar_path_abs.write_bytes(tar_bytes_abs)

    with pytest.raises(ZipSlipSecurityError, match=r"(?i)symlink|path traversal|escaping|tar-slip|zip-slip"):
        safe_extract_tar(tar_path_abs, dest_dir)


def test_safe_extract_archive_delegates_zip_and_tar(tmp_path: Path) -> None:
    """safe_extract_archive routes .zip to safe_extract_zip and .tar.gz/.tgz to safe_extract_tar."""
    zip_path = tmp_path / "archive.zip"
    tar_path = tmp_path / "archive.tar.gz"
    tgz_path = tmp_path / "archive.tgz"
    target_dir = tmp_path / "target"

    with (
        patch("core.runtime_manager.safe_extract_zip") as mock_zip,
        patch("core.runtime_manager.safe_extract_tar") as mock_tar,
    ):
        safe_extract_archive(zip_path, target_dir)
        mock_zip.assert_called_once_with(zip_path, target_dir)
        mock_tar.assert_not_called()

        mock_zip.reset_mock()
        safe_extract_archive(tar_path, target_dir)
        mock_tar.assert_called_once_with(tar_path, target_dir)
        mock_zip.assert_not_called()

        mock_tar.reset_mock()
        safe_extract_archive(tgz_path, target_dir)
        mock_tar.assert_called_once_with(tgz_path, target_dir)
        mock_zip.assert_not_called()

    bad_path = tmp_path / "archive.7z"
    with pytest.raises(ValueError, match=r"(?i)unsupported"):
        safe_extract_archive(bad_path, target_dir)


def test_validate_runtime_binary_linux_prepends_ld_library_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux runtime binary validation prepends runtime directory to LD_LIBRARY_PATH for dynamic linking."""
    monkeypatch.setattr("sys.platform", "linux")
    exe = tmp_path / "fake-server"
    exe.write_bytes(b"\x7fELF mock binary")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert validate_runtime_binary(exe) is True

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert "env" in kwargs, "validate_runtime_binary must pass env dict on Linux"
        run_env = kwargs["env"]
        assert "LD_LIBRARY_PATH" in run_env, "LD_LIBRARY_PATH must be set in subprocess env"
        assert str(exe.parent) in run_env["LD_LIBRARY_PATH"]


def test_get_runtime_base_dir_linux_xdg_parity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Linux runtime directory honors XDG_DATA_HOME with fallback to ~/.local/share."""
    monkeypatch.setattr("sys.platform", "linux")

    # Case 1: Custom XDG_DATA_HOME
    custom_xdg = tmp_path / "custom_xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(custom_xdg))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    resolved = get_runtime_base_dir()
    expected_custom = custom_xdg / "aksarasight" / "runtimes" / "llama-cpp"
    assert resolved == expected_custom
    assert "AksaraSight" not in resolved.parts
    assert "aksarasight" in resolved.parts

    # Case 2: Default XDG location (~/.local/share/aksarasight/runtimes/llama-cpp)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    fake_home = tmp_path / "user_home"
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    resolved_default = get_runtime_base_dir()
    expected_default = fake_home / ".local" / "share" / "aksarasight" / "runtimes" / "llama-cpp"
    assert resolved_default == expected_default
    assert "AksaraSight" not in resolved_default.parts
    assert "aksarasight" in resolved_default.parts


def test_resolve_asset_names_linux_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux asset resolution works for both resolve_asset_names and resolve_required_asset_names."""
    monkeypatch.setattr("sys.platform", "linux")
    assert resolve_asset_names("vulkan", "b11361") == ["llama-b11361-bin-ubuntu-vulkan-x64.tar.gz"]
    assert resolve_asset_names("cpu", "b11361") == ["llama-b11361-bin-ubuntu-x64.tar.gz"]
    assert resolve_asset_names("vulkan", "b11361") == resolve_required_asset_names("vulkan", "b11361")


def test_ensure_runtime_linux_tar_gz_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Linux tar.gz complete download, extraction, validation, and manifest creation flow with unmocked resolver."""
    monkeypatch.setattr("sys.platform", "linux")
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        tar_bytes = _create_test_tar(
            {"llama-b11361/llama-server": b"fake-server-binary"},
            executable_files={"llama-b11361/llama-server"},
        )
        tar_digest = hashlib.sha256(tar_bytes).hexdigest()
        asset_name = "llama-b11361-bin-ubuntu-vulkan-x64.tar.gz"

        mock_meta = {
            asset_name: ReleaseAssetInfo(
                name=asset_name,
                download_url="https://mock/vulkan.tar.gz",
                size=len(tar_bytes),
                digest=f"sha256:{tar_digest}",
            )
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Length": str(len(tar_bytes))}
        mock_resp.iter_content.return_value = [tar_bytes]
        mock_resp.__enter__.return_value = mock_resp

        mock_session = MagicMock(spec=requests.Session)
        mock_session.get.return_value = mock_resp

        with (
            patch("core.runtime_manager.fetch_release_assets_metadata", return_value=mock_meta),
            patch("core.runtime_manager.validate_runtime_binary", return_value=True),
            patch.dict("core.runtime_manager.KNOWN_PINNED_HASHES", {asset_name: tar_digest}),
        ):
            # Unmocked resolve_asset_names(backend, tag) resolves "llama-b11361-bin-ubuntu-vulkan-x64.tar.gz"
            final_exe = ensure_runtime(backend="vulkan", tag="b11361", session=mock_session)

            assert final_exe.is_file()
            assert final_exe.name == "llama-server"
            runtime_dir = get_runtime_dir("b11361", "vulkan")
            assert (runtime_dir / "llama-server").is_file()
            assert (runtime_dir / "manifest.json").is_file()
            assert is_runtime_installed("vulkan", "b11361") is True
            assert not (tmp_path / "downloads" / asset_name).exists()


def test_safe_extract_tar_existing_dest_unlink_and_oserror_handling(tmp_path: Path) -> None:
    """safe_extract_tar unlinks pre-existing file or symlink at symlink dest, handling OSError gracefully."""
    tar_bytes = _create_test_tar(
        files={"llama-b11361/libllama.so": b"binary-data"},
        symlinks={"llama-b11361/libllama.so.0": "libllama.so"},
    )
    tar_path = tmp_path / "runtime.tar.gz"
    tar_path.write_bytes(tar_bytes)

    dest_dir = tmp_path / "extracted"
    dest_dir.mkdir()

    # Pre-create the destination file so dest.exists() is True
    existing_dest = dest_dir / "libllama.so.0"
    existing_dest.write_text("old version", encoding="utf-8")

    # 1. Normal unlink: pre-existing file is unlinked and replaced
    safe_extract_tar(tar_path, dest_dir)
    assert existing_dest.exists()

    # 2. dest.unlink() raises OSError
    tar_path2 = tmp_path / "runtime2.tar.gz"
    tar_path2.write_bytes(tar_bytes)
    dest_dir2 = tmp_path / "extracted2"
    dest_dir2.mkdir()
    existing_dest2 = dest_dir2 / "libllama.so.0"
    existing_dest2.write_text("old", encoding="utf-8")

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self == existing_dest2:
            raise OSError("Access denied unlinking")
        return real_unlink(self, *args, **kwargs)

    with patch.object(Path, "unlink", failing_unlink):
        safe_extract_tar(tar_path2, dest_dir2)


def test_safe_extract_tar_symlink_oserror_fallback_to_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When os.symlink raises OSError, safe_extract_tar copies the target file as fallback."""
    tar_bytes = _create_test_tar(
        files={"llama-b11361/libllama.so": b"shared-lib-bytes"},
        symlinks={"llama-b11361/libllama.so.0": "libllama.so"},
    )
    tar_path = tmp_path / "runtime.tar.gz"
    tar_path.write_bytes(tar_bytes)

    dest_dir = tmp_path / "extracted"

    # Make os.symlink fail with OSError (e.g. unprivileged non-elevated symlink)
    def failing_symlink(src, dst):
        raise OSError("Privilege not held for symlink creation")

    monkeypatch.setattr(os, "symlink", failing_symlink)

    safe_extract_tar(tar_path, dest_dir)

    target_symlink = dest_dir / "libllama.so.0"
    assert target_symlink.is_file()
    assert not target_symlink.is_symlink()
    assert target_symlink.read_bytes() == b"shared-lib-bytes"


def test_validate_runtime_binary_win32_error_mode_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """validate_runtime_binary on Win32 sets SEM_FAILCRITICALERRORS and restores prev_mode in finally."""
    import ctypes
    import types

    monkeypatch.setattr(sys, "platform", "win32")
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"MZ\x90mock-exe")

    mock_k32 = MagicMock()
    mock_k32.GetErrorMode.return_value = 0x0004
    mock_windll = types.SimpleNamespace(kernel32=mock_k32)
    monkeypatch.setattr(ctypes, "windll", mock_windll, raising=False)

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        assert validate_runtime_binary(exe) is True

    mock_k32.GetErrorMode.assert_called_once()
    # 0x0004 | 0x0001 | 0x0002 = 0x0007
    mock_k32.SetErrorMode.assert_any_call(0x0007)
    # finally restores original
    assert mock_k32.SetErrorMode.call_args[0][0] == 0x0004


def test_validate_runtime_binary_win32_get_error_mode_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When GetErrorMode raises, fallback calls SetErrorMode with flags and restores in finally."""
    import ctypes
    import types

    monkeypatch.setattr(sys, "platform", "win32")
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"MZ\x90mock-exe")

    mock_k32 = MagicMock()
    mock_k32.GetErrorMode.side_effect = RuntimeError("No GetErrorMode")
    mock_k32.SetErrorMode.return_value = 0x0000
    mock_windll = types.SimpleNamespace(kernel32=mock_k32)
    monkeypatch.setattr(ctypes, "windll", mock_windll, raising=False)

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        assert validate_runtime_binary(exe) is True

    mock_k32.SetErrorMode.assert_any_call(0x0001 | 0x0002)


def test_validate_runtime_binary_win32_set_error_mode_finally_exception_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exceptions raised by SetErrorMode in finally are swallowed without crashing."""
    import ctypes
    import types

    monkeypatch.setattr(sys, "platform", "win32")
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"MZ\x90mock-exe")

    mock_k32 = MagicMock()
    mock_k32.GetErrorMode.return_value = 0x0001
    mock_k32.SetErrorMode.side_effect = [0x0001, RuntimeError("Restoration crash")]
    mock_windll = types.SimpleNamespace(kernel32=mock_k32)
    monkeypatch.setattr(ctypes, "windll", mock_windll, raising=False)

    with patch("subprocess.run", return_value=MagicMock(returncode=0)):
        assert validate_runtime_binary(exe) is True


def test_is_runtime_installed_corrupted_manifest(tmp_path: Path) -> None:
    """is_runtime_installed returns False when manifest.json is invalid JSON."""
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        runtime_dir = get_runtime_dir("b11361", "vulkan")
        runtime_dir.mkdir(parents=True)
        exe_name = "llama-server" if sys.platform != "win32" else "llama-server.exe"
        (runtime_dir / exe_name).write_bytes(b"bin")
        (runtime_dir / "manifest.json").write_text("{corrupt json", encoding="utf-8")

        assert is_runtime_installed("vulkan", "b11361") is False


def test_get_installed_runtime_path_argument_reversal(tmp_path: Path) -> None:
    """get_installed_runtime_path swaps backend and tag when passed in reversed order."""
    with patch("core.runtime_manager.get_runtime_base_dir", return_value=tmp_path):
        runtime_dir = get_runtime_dir("b11361", "vulkan")
        runtime_dir.mkdir(parents=True)
        exe_name = "llama-server" if sys.platform != "win32" else "llama-server.exe"
        exe_file = runtime_dir / exe_name
        exe_file.write_bytes(b"bin")
        manifest = '{"tag": "b11361", "backend": "vulkan"}'
        (runtime_dir / "manifest.json").write_text(manifest, encoding="utf-8")

        resolved = get_installed_runtime_path("vulkan", "b11361")
        assert resolved == exe_file


def test_resolve_effective_server_path_none_settings() -> None:
    """resolve_effective_server_path returns None when settings is None."""
    assert resolve_effective_server_path(None) is None

