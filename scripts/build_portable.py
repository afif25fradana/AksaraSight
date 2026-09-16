"""Automated build and packaging script for AksaraSight Local Portable Windows Distribution.

Orchestrates:
1. Pre-build environment and dependency validation.
2. Clean build directory initialization.
3. PyInstaller compilation using build_portable.spec.
4. Post-build binary and asset integrity checks.
5. Portable zip archive packaging (AksaraSight-v<version>-windows-x64.zip).
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

# Ensure project root is in sys.path to import core.constants
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.constants import __version__


def check_environment() -> None:
    """Validate that required build dependencies are installed."""
    print("=" * 60)
    print(f"AksaraSight Portable Distribution Builder — v{__version__}")
    print("=" * 60)
    print(f"Python Runtime: {sys.version.split()[0]} ({sys.platform})")
    print(f"Repository Root: {REPO_ROOT}")

    try:
        import PyInstaller
        print(f"PyInstaller Version: {PyInstaller.__version__}")
    except ImportError:
        sys.stderr.write("ERROR: PyInstaller is not installed. Run 'pip install -r requirements-build.txt'\n")
        sys.exit(1)


def clean_build_directories() -> None:
    """Remove previous build artifacts and dist/AksaraSight directory."""
    print("\n[1/4] Cleaning previous build artifacts...")
    for folder_name in ["build", "dist/AksaraSight"]:
        target = REPO_ROOT / folder_name
        if target.exists():
            print(f"  Removing {target}...")
            shutil.rmtree(target, ignore_errors=True)


def run_pyinstaller() -> None:
    """Execute PyInstaller against build_portable.spec."""
    print("\n[2/4] Executing PyInstaller build...")
    spec_path = REPO_ROOT / "build_portable.spec"
    if not spec_path.is_file():
        sys.stderr.write(f"ERROR: Spec file not found at {spec_path}\n")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        str(spec_path),
    ]
    print(f"  Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        sys.stderr.write(f"\nERROR: PyInstaller build failed with exit code {result.returncode}\n")
        sys.exit(result.returncode)


def verify_bundle_integrity() -> Path:
    """Verify that expected binaries and required runtime assets were collected."""
    print("\n[3/4] Verifying bundle integrity...")
    dist_dir = REPO_ROOT / "dist" / "AksaraSight"
    if not dist_dir.is_dir():
        sys.stderr.write(f"ERROR: Expected distribution directory not found: {dist_dir}\n")
        sys.exit(1)

    # Configure utf-8 stdout if possible
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 1. Executables check
    gui_exe = dist_dir / "AksaraSight.exe"
    cli_exe = dist_dir / "AksaraSight-CLI.exe"

    for exe, label in [(gui_exe, "Desktop Studio GUI"), (cli_exe, "Console CLI")]:
        if not exe.is_file():
            sys.stderr.write(f"ERROR: Missing executable: {exe.name} ({label})\n")
            sys.exit(1)
        size_kb = exe.stat().st_size / 1024
        print(f"  [OK] {exe.name} ({label}): {size_kb:.1f} KB")

    # 2. _internal directory check
    internal_dir = dist_dir / "_internal"
    if not internal_dir.is_dir():
        sys.stderr.write("ERROR: Missing _internal runtime directory\n")
        sys.exit(1)

    # 3. Native DLL check (pdfium.dll)
    pdfium_matches = list(internal_dir.rglob("pdfium.dll"))
    if not pdfium_matches:
        sys.stderr.write("ERROR: pdfium.dll not found in _internal directory!\n")
        sys.exit(1)
    print(f"  [OK] Native PDFium DLL: {pdfium_matches[0].relative_to(dist_dir)}")

    # 4. CustomTkinter assets check
    ctk_themes = list(internal_dir.rglob("assets/themes")) + list(internal_dir.rglob("themes"))
    if not ctk_themes:
        sys.stderr.write("ERROR: customtkinter theme assets not found in _internal!\n")
        sys.exit(1)
    print(f"  [OK] CustomTkinter assets: {ctk_themes[0].relative_to(dist_dir)}")

    # 5. TkinterDnD2 tkdnd check
    tkdnd_dirs = list(internal_dir.rglob("tkdnd"))
    if not tkdnd_dirs:
        sys.stderr.write("ERROR: tkinterdnd2 tkdnd binaries not found in _internal!\n")
        sys.exit(1)
    print(f"  [OK] TkinterDnD2 binaries: {tkdnd_dirs[0].relative_to(dist_dir)}")

    return dist_dir


def package_zip_archive(dist_dir: Path) -> Path:
    """Package the dist/AksaraSight folder into a portable zip archive."""
    print("\n[4/4] Creating portable distribution zip archive...")
    zip_name = f"AksaraSight-v{__version__}-windows-x64.zip"
    zip_path = REPO_ROOT / "dist" / zip_name

    if zip_path.exists():
        zip_path.unlink()

    print(f"  Target: {zip_path.name}")
    file_count = 0
    total_bytes = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(dist_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = Path("AksaraSight") / file_path.relative_to(dist_dir)
                zf.write(file_path, arcname=str(arcname))
                file_count += 1
                total_bytes += file_path.stat().st_size

    zip_mb = zip_path.stat().st_size / (1024 * 1024)
    uncomp_mb = total_bytes / (1024 * 1024)
    ratio = (1.0 - (zip_path.stat().st_size / total_bytes)) * 100 if total_bytes > 0 else 0

    print(f"  Files Bundled: {file_count}")
    print(f"  Uncompressed:  {uncomp_mb:.1f} MB")
    print(f"  Compressed:    {zip_mb:.1f} MB (Compression: {ratio:.1f}%)")
    print(f"  Portable ZIP:  {zip_path.resolve()}")
    return zip_path


def main() -> None:
    """Execute the full build workflow."""
    check_environment()
    clean_build_directories()
    run_pyinstaller()
    dist_dir = verify_bundle_integrity()
    zip_path = package_zip_archive(dist_dir)
    print("\n" + "=" * 60)
    print(f"BUILD COMPLETE: {zip_path.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
