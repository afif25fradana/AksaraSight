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
import tarfile
from typing import Optional
import zipfile

# Ensure project root is in sys.path to import core.constants
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.constants import __version__


def _resolve_exe_name(base_name: str) -> str:
    """Resolve platform-specific executable name."""
    if sys.platform == "win32":
        return f"{base_name}.exe" if not base_name.endswith(".exe") else base_name
    return base_name[:-4] if base_name.endswith(".exe") else base_name


def check_environment() -> None:
    """Validate that required build dependencies are installed."""
    print("=" * 60)
    print(f"AksaraSight Portable Distribution Builder: v{__version__}")
    print("=" * 60)
    print(f"Python Runtime: {sys.version.split()[0]} ({sys.platform})")
    print(f"Repository Root: {REPO_ROOT}")

    try:
        import PyInstaller
        print(f"PyInstaller Version: {PyInstaller.__version__}")
    except ImportError:
        sys.stderr.write("ERROR: PyInstaller is not installed. Run 'pip install -r requirements-build.txt'\n")
        sys.exit(1)

    web_static_html = REPO_ROOT / "web" / "static" / "index.html"
    if not web_static_html.is_file():
        sys.stderr.write(f"ERROR: Web UI static bundle not found at {web_static_html}. Build frontend before packaging.\n")
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
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    gui_exe = dist_dir / _resolve_exe_name("AksaraSight")
    cli_exe = dist_dir / _resolve_exe_name("AksaraSight-CLI")

    for exe, label in [(gui_exe, "Web UI Desktop Server"), (cli_exe, "Console CLI")]:
        if not exe.is_file():
            sys.stderr.write(f"ERROR: Missing executable: {exe.name} ({label})\n")
            sys.exit(1)
        if sys.platform != "win32" and not os.access(exe, os.X_OK):
            sys.stderr.write(f"ERROR: Executable lacks execute permission: {exe.name} ({label})\n")
            sys.exit(1)
        size_kb = exe.stat().st_size / 1024
        print(f"  [OK] {exe.name} ({label}): {size_kb:.1f} KB")

    internal_dir = dist_dir / "_internal"
    if not internal_dir.is_dir():
        sys.stderr.write("ERROR: Missing _internal runtime directory\n")
        sys.exit(1)

    if sys.platform == "win32":
        pdfium_matches = list(internal_dir.rglob("pdfium.dll"))
        lib_name = "pdfium.dll"
    else:
        pdfium_matches = list(internal_dir.rglob("*pdfium*.so*"))
        lib_name = "*pdfium*.so*"

    if not pdfium_matches:
        sys.stderr.write(f"ERROR: {lib_name} not found in _internal directory!\n")
        sys.exit(1)
    print(f"  [OK] Native PDFium library: {pdfium_matches[0].relative_to(dist_dir)}")

    web_static_html = internal_dir / "web" / "static" / "index.html"
    if not web_static_html.is_file():
        sys.stderr.write(f"ERROR: Web UI index.html not found in _internal: {web_static_html}\n")
        sys.exit(1)
    print(f"  [OK] Web UI HTML entrypoint: {web_static_html.relative_to(dist_dir)}")

    web_static_css = internal_dir / "web" / "static" / "assets" / "index.css"
    if not web_static_css.is_file():
        sys.stderr.write(f"ERROR: Web UI index.css not found in _internal: {web_static_css}\n")
        sys.exit(1)
    print(f"  [OK] Web UI stylesheet: {web_static_css.relative_to(dist_dir)}")

    web_static_js = internal_dir / "web" / "static" / "assets" / "index.js"
    if not web_static_js.is_file():
        sys.stderr.write(f"ERROR: Web UI JavaScript bundle not found in _internal: {web_static_js}\n")
        sys.exit(1)
    print(f"  [OK] Web UI script bundle: {web_static_js.relative_to(dist_dir)}")

    docx_templates = list(internal_dir.rglob("default.docx"))
    if not docx_templates:
        sys.stderr.write("ERROR: python-docx default.docx template not found in _internal!\n")
        sys.exit(1)
    print(f"  [OK] python-docx template: {docx_templates[0].relative_to(dist_dir)}")

    return dist_dir


def package_distribution_archive(dist_dir: Path, output_dir: Optional[Path] = None) -> Path:
    """Package the dist/AksaraSight folder into a platform-appropriate archive."""
    target_dir = output_dir if output_dir is not None else REPO_ROOT / "dist"
    target_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        print("\n[4/4] Creating portable distribution zip archive...")
        zip_name = f"AksaraSight-v{__version__}-windows-x64.zip"
        zip_path = target_dir / zip_name

        if zip_path.exists():
            zip_path.unlink()

        print(f"  Target: {zip_path.name}")
        file_count = 0
        total_bytes = 0

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root, dirs, files in os.walk(dist_dir):
                for file in files:
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(dist_dir)
                    arcname = Path("AksaraSight") / rel_path
                    zf.write(file_path, arcname=str(arcname).replace("\\", "/"))
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
    else:
        print("\n[4/4] Creating portable distribution tar.gz archive...")
        tar_name = f"AksaraSight-v{__version__}-linux-x64.tar.gz"
        tar_path = target_dir / tar_name

        if tar_path.exists():
            tar_path.unlink()

        print(f"  Target: {tar_path.name}")

        def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
            tarinfo.name = tarinfo.name.replace("\\", "/")
            if tarinfo.isdir():
                tarinfo.mode = 0o755
            elif (
                tarinfo.name in ("AksaraSight/AksaraSight", "AksaraSight/AksaraSight-CLI")
                or tarinfo.name.endswith("/AksaraSight")
                or tarinfo.name.endswith("/AksaraSight-CLI")
                or (tarinfo.mode & 0o111) != 0
            ):
                tarinfo.mode = 0o755
            return tarinfo

        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(str(dist_dir), arcname="AksaraSight", filter=_tar_filter)

        tar_mb = tar_path.stat().st_size / (1024 * 1024)
        print(f"  Compressed:    {tar_mb:.1f} MB")
        print(f"  Portable TAR:  {tar_path.resolve()}")
        return tar_path


package_archive = package_distribution_archive
package_zip_archive = package_distribution_archive


def main() -> None:
    """Execute the full build workflow."""
    check_environment()
    clean_build_directories()
    run_pyinstaller()
    dist_dir = verify_bundle_integrity()
    archive_path = package_distribution_archive(dist_dir)
    print("\n" + "=" * 60)
    print(f"BUILD COMPLETE: {archive_path.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
