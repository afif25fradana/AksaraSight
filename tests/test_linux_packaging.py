"""Tests for Linux packaging, platform executable resolution, and frozen verification."""

import os
from pathlib import Path
import sys
import tarfile
from typing import Callable
import zipfile
import pytest


# ---------------------------------------------------------------------------
# Section 1: Platform Executable Resolution
# ---------------------------------------------------------------------------

def test_build_portable_resolve_exe_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """scripts/build_portable.py must resolve platform-aware executable names."""
    import scripts.build_portable as build_portable

    assert hasattr(build_portable, "_resolve_exe_name"), (
        "scripts/build_portable.py must export _resolve_exe_name(base_name)"
    )
    resolve_exe = getattr(build_portable, "_resolve_exe_name")

    monkeypatch.setattr(sys, "platform", "win32")
    assert resolve_exe("AksaraSight") == "AksaraSight.exe"
    assert resolve_exe("AksaraSight-CLI") == "AksaraSight-CLI.exe"

    monkeypatch.setattr(sys, "platform", "linux")
    assert resolve_exe("AksaraSight") == "AksaraSight"
    assert resolve_exe("AksaraSight-CLI") == "AksaraSight-CLI"


def test_verify_frozen_build_resolve_exe_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """scripts/verify_frozen_build.py must resolve platform-aware executable names."""
    import scripts.verify_frozen_build as verify_frozen_build

    assert hasattr(verify_frozen_build, "_resolve_exe_name"), (
        "scripts/verify_frozen_build.py must export _resolve_exe_name(base_name)"
    )
    resolve_exe = getattr(verify_frozen_build, "_resolve_exe_name")

    monkeypatch.setattr(sys, "platform", "win32")
    assert resolve_exe("AksaraSight") == "AksaraSight.exe"
    assert resolve_exe("AksaraSight-CLI") == "AksaraSight-CLI.exe"

    monkeypatch.setattr(sys, "platform", "linux")
    assert resolve_exe("AksaraSight") == "AksaraSight"
    assert resolve_exe("AksaraSight-CLI") == "AksaraSight-CLI"


# ---------------------------------------------------------------------------
# Section 2: Platform Archive Packaging
# ---------------------------------------------------------------------------

def _get_archive_packager() -> Callable[..., Path]:
    import scripts.build_portable as build_portable

    pkg_func = getattr(build_portable, "package_distribution_archive", None) or getattr(
        build_portable, "package_archive", None
    )
    assert pkg_func is not None, (
        "scripts/build_portable.py must export package_distribution_archive(dist_dir) or package_archive(dist_dir)"
    )
    return pkg_func


def test_package_archive_windows_produces_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows, packaging helper must produce a .zip archive rooted at AksaraSight/."""
    monkeypatch.setattr(sys, "platform", "win32")
    packager = _get_archive_packager()

    dist_dir = tmp_path / "dist" / "AksaraSight"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "AksaraSight.exe").write_text("mock gui exe", encoding="utf-8")
    (dist_dir / "AksaraSight-CLI.exe").write_text("mock cli exe", encoding="utf-8")
    internal_dir = dist_dir / "_internal"
    internal_dir.mkdir(parents=True, exist_ok=True)
    (internal_dir / "resource.txt").write_text("mock resource", encoding="utf-8")

    archive_path: Path
    try:
        archive_path = packager(dist_dir, output_dir=tmp_path / "dist")
    except TypeError:
        archive_path = packager(dist_dir)

    assert archive_path.is_file(), f"Expected archive file not found: {archive_path}"
    assert archive_path.suffix == ".zip"
    assert "windows" in archive_path.name.lower()

    with zipfile.ZipFile(archive_path, "r") as zf:
        names = zf.namelist()
        assert len(names) >= 3
        assert all(n.startswith("AksaraSight/") for n in names)
        assert "AksaraSight/AksaraSight.exe" in names
        assert "AksaraSight/AksaraSight-CLI.exe" in names
        assert "AksaraSight/_internal/resource.txt" in names


def test_package_archive_linux_produces_tar_gz_with_root_and_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Linux, packaging helper must produce .tar.gz with AksaraSight/ root and 0o755 permissions."""
    monkeypatch.setattr(sys, "platform", "linux")
    packager = _get_archive_packager()

    dist_dir = tmp_path / "dist" / "AksaraSight"
    dist_dir.mkdir(parents=True, exist_ok=True)
    gui_bin = dist_dir / "AksaraSight"
    gui_bin.write_text("#!/bin/sh\necho gui", encoding="utf-8")
    cli_bin = dist_dir / "AksaraSight-CLI"
    cli_bin.write_text("#!/bin/sh\necho cli", encoding="utf-8")
    internal_dir = dist_dir / "_internal"
    internal_dir.mkdir(parents=True, exist_ok=True)
    res_file = internal_dir / "resource.txt"
    res_file.write_text("mock resource", encoding="utf-8")

    # Set executable modes if on POSIX
    if os.name == "posix":
        gui_bin.chmod(0o755)
        cli_bin.chmod(0o755)
        res_file.chmod(0o644)

    archive_path: Path
    try:
        archive_path = packager(dist_dir, output_dir=tmp_path / "dist")
    except TypeError:
        archive_path = packager(dist_dir)

    assert archive_path.is_file(), f"Expected archive file not found: {archive_path}"
    assert archive_path.name.endswith(".tar.gz")
    assert "linux" in archive_path.name.lower()

    with tarfile.open(archive_path, "r:gz") as tf:
        members = tf.getmembers()
        assert len(members) >= 3
        member_names = [m.name for m in members]
        assert all(n.startswith("AksaraSight/") or n == "AksaraSight" for n in member_names)
        assert "AksaraSight/AksaraSight" in member_names
        assert "AksaraSight/AksaraSight-CLI" in member_names
        assert "AksaraSight/_internal/resource.txt" in member_names

        # Executable binaries must preserve executable permission (0o755)
        gui_member = tf.getmember("AksaraSight/AksaraSight")
        cli_member = tf.getmember("AksaraSight/AksaraSight-CLI")
        assert (gui_member.mode & 0o111) != 0, (
            f"AksaraSight missing executable permission in tar.gz: mode={oct(gui_member.mode)}"
        )
        assert (cli_member.mode & 0o111) != 0, (
            f"AksaraSight-CLI missing executable permission in tar.gz: mode={oct(cli_member.mode)}"
        )


# ---------------------------------------------------------------------------
# Section 3: Frozen Log Path Resolution (scripts/verify_frozen_build.py)
# ---------------------------------------------------------------------------

def _get_frozen_log_resolver() -> Callable[[], Path]:
    import scripts.verify_frozen_build as verify_frozen_build

    for candidate in ("_resolve_frozen_log_path", "_resolve_log_path", "_get_log_file_path"):
        if hasattr(verify_frozen_build, candidate):
            return getattr(verify_frozen_build, candidate)
    raise AttributeError(
        "scripts/verify_frozen_build.py must export _resolve_frozen_log_path() or _resolve_log_path()"
    )


def test_verify_frozen_log_path_preserves_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When LOCALAPPDATA is set, log resolver must target %LOCALAPPDATA%/AksaraSight/logs/app.log."""
    custom_appdata = tmp_path / "custom_appdata"
    monkeypatch.setenv("LOCALAPPDATA", str(custom_appdata))

    resolver = _get_frozen_log_resolver()
    resolved = resolver()
    assert resolved == custom_appdata / "AksaraSight" / "logs" / "app.log"


def test_verify_frozen_log_path_windows_fallback_when_localappdata_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When LOCALAPPDATA is unset on Windows, log resolver defaults to ~/AppData/Local/AksaraSight/logs/app.log."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    fake_home = tmp_path / "mock_win_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    resolver = _get_frozen_log_resolver()
    resolved = resolver()
    assert resolved == fake_home / "AppData" / "Local" / "AksaraSight" / "logs" / "app.log"


def test_verify_frozen_log_path_linux_xdg_state_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Linux with LOCALAPPDATA unset, log resolver targets $XDG_STATE_HOME/aksarasight/logs/app.log."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")

    custom_xdg = tmp_path / "mock_xdg"
    monkeypatch.setenv("XDG_STATE_HOME", str(custom_xdg))

    resolver = _get_frozen_log_resolver()
    resolved = resolver()
    assert resolved == custom_xdg / "aksarasight" / "logs" / "app.log"


def test_verify_frozen_log_path_linux_default_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Linux with LOCALAPPDATA & XDG_STATE_HOME unset, log resolver defaults to ~/.local/state/aksarasight/logs/app.log."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")

    fake_home = tmp_path / "mock_linux_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    resolver = _get_frozen_log_resolver()
    resolved = resolver()
    assert resolved == fake_home / ".local" / "state" / "aksarasight" / "logs" / "app.log"


def test_verify_frozen_log_file_linux_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test_frozen_log_file() on Linux must find and verify log file under XDG state home."""
    import scripts.verify_frozen_build as verify_frozen_build

    fake_home = tmp_path / "mock_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")

    custom_xdg = tmp_path / "xdg_state"
    monkeypatch.setenv("XDG_STATE_HOME", str(custom_xdg))

    log_file = custom_xdg / "aksarasight" / "logs" / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(
        f"Frozen application started (v{verify_frozen_build.__version__})\n",
        encoding="utf-8",
    )

    assert verify_frozen_build.test_frozen_log_file() is True


# ---------------------------------------------------------------------------
# Section 4: Bundle Integrity Verification (scripts/build_portable.py)
# ---------------------------------------------------------------------------

def _setup_mock_linux_bundle(
    tmp_path: Path,
    include_pdfium: bool = True,
    executable_gui: bool = True,
    executable_cli: bool = True,
) -> Path:
    dist_dir = tmp_path / "dist" / "AksaraSight"
    dist_dir.mkdir(parents=True, exist_ok=True)

    gui_bin = dist_dir / "AksaraSight"
    gui_bin.write_bytes(b"\x7fELF mock gui")
    cli_bin = dist_dir / "AksaraSight-CLI"
    cli_bin.write_bytes(b"\x7fELF mock cli")

    if os.name == "posix":
        gui_bin.chmod(0o755 if executable_gui else 0o644)
        cli_bin.chmod(0o755 if executable_cli else 0o644)

    internal_dir = dist_dir / "_internal"
    internal_dir.mkdir(parents=True, exist_ok=True)

    if include_pdfium:
        (internal_dir / "libpdfium.so").write_bytes(b"mock pdfium shared lib")

    web_static_assets = internal_dir / "web" / "static" / "assets"
    web_static_assets.mkdir(parents=True, exist_ok=True)
    (internal_dir / "web" / "static" / "index.html").write_text("<!DOCTYPE html>", encoding="utf-8")
    (web_static_assets / "index.css").write_text("body {}", encoding="utf-8")
    (web_static_assets / "index.js").write_text("console.log()", encoding="utf-8")

    templates_dir = internal_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    (templates_dir / "default.docx").write_bytes(b"mock docx template")

    return dist_dir


def test_verify_bundle_integrity_linux_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """verify_bundle_integrity() succeeds when all required Linux binaries and assets are present."""
    import scripts.build_portable as build_portable

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(build_portable, "REPO_ROOT", tmp_path)

    dist_dir = _setup_mock_linux_bundle(tmp_path)
    verified = build_portable.verify_bundle_integrity()
    assert verified == dist_dir


def test_verify_bundle_integrity_linux_missing_pdfium_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """verify_bundle_integrity() exits with SystemExit(1) when libpdfium.so is missing from _internal."""
    import scripts.build_portable as build_portable

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(build_portable, "REPO_ROOT", tmp_path)

    _setup_mock_linux_bundle(tmp_path, include_pdfium=False)
    with pytest.raises(SystemExit) as exc_info:
        build_portable.verify_bundle_integrity()
    assert exc_info.value.code == 1


def test_verify_bundle_integrity_linux_non_executable_binary_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """verify_bundle_integrity() exits with SystemExit(1) when binary lacks execute permission."""
    import scripts.build_portable as build_portable

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(build_portable, "REPO_ROOT", tmp_path)

    dist_dir = _setup_mock_linux_bundle(tmp_path, executable_gui=False)
    gui_bin = dist_dir / "AksaraSight"

    if os.name != "posix":
        real_access = os.access
        monkeypatch.setattr(
            os,
            "access",
            lambda p, m: False if (m == os.X_OK and Path(p) == gui_bin) else real_access(p, m),
        )

    with pytest.raises(SystemExit) as exc_info:
        build_portable.verify_bundle_integrity()
    assert exc_info.value.code == 1
