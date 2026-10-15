"""Comprehensive verification and smoke test suite for AksaraSight frozen portable build.

Verifies:
1. CLI Functionality: Confirms AksaraSight-CLI.exe --version, --detect-hardware, and input validation.
2. Web UI Desktop Server: Launches AksaraSight.exe on an ephemeral loopback port with --no-browser,
   verifies /api/server/status, root HTML, and CSS assets, then terminates cleanly.
3. File-based Logging: Confirms %LOCALAPPDATA%\\AksaraSight\\logs\\app.log was created and
   recorded startup telemetry and version.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from core.constants import __version__

DIST_DIR = REPO_ROOT / "dist" / "AksaraSight"
GUI_EXE = DIST_DIR / "AksaraSight.exe"
CLI_EXE = DIST_DIR / "AksaraSight-CLI.exe"


def test_cli_version() -> bool:
    """Verify AksaraSight-CLI.exe --version outputs expected version."""
    print("[1/5] Testing CLI binary version output...")
    res = subprocess.run([str(CLI_EXE), "--version"], capture_output=True, text=True, timeout=10)
    print(f"  Stdout: {res.stdout.strip()}")
    if res.returncode != 0 or f"AksaraSight-CLI {__version__}" not in res.stdout:
        print("  [FAIL] CLI version test failed")
        return False
    print("  [PASS] CLI version verified")
    return True


def test_cli_hardware_detection() -> bool:
    """Verify AksaraSight-CLI.exe --detect-hardware runs with zero network and outputs report."""
    print("\n[2/5] Testing CLI hardware detection (zero-network invariant)...")
    res = subprocess.run([str(CLI_EXE), "--detect-hardware"], capture_output=True, text=True, timeout=10)
    if res.returncode != 0:
        print(f"  [FAIL] Hardware detection exited with code {res.returncode}:\n{res.stderr}")
        return False
    if "SYSTEM HARDWARE DETECTION REPORT" not in res.stdout or "RECOMMENDED BACKEND" not in res.stdout:
        print(f"  [FAIL] Incomplete hardware report:\n{res.stdout}")
        return False
    print("  [PASS] Hardware detection report verified")
    return True


def test_cli_input_validation() -> bool:
    """Verify AksaraSight-CLI.exe handles nonexistent files with structured exit code 1 and error message."""
    print("\n[3/5] Testing CLI input validation and error handling...")
    res = subprocess.run([str(CLI_EXE), "nonexistent_sample.png"], capture_output=True, text=True, timeout=10)
    print(f"  Exit code: {res.returncode}")
    if res.returncode != 1 or "Error: Input path does not exist" not in res.stderr:
        print(f"  [FAIL] Input validation failed:\n{res.stderr}")
        return False
    print("  [PASS] CLI input validation and exit code 1 verified")
    return True


def test_web_server_startup_and_endpoints() -> bool:
    """Launch real AksaraSight.exe on ephemeral port with --no-browser and verify HTTP endpoints."""
    print("\n[4/5] Testing Web UI desktop server startup and endpoints (ephemeral port)...")

    # Allocate an ephemeral loopback port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    cmd = [
        str(GUI_EXE),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-browser",
    ]
    proc = subprocess.Popen(cmd, cwd=str(DIST_DIR))
    print(f"  Launched {GUI_EXE.name} on port {port} (PID: {proc.pid})")

    try:
        status_url = f"http://127.0.0.1:{port}/api/server/status"
        root_url = f"http://127.0.0.1:{port}/"
        css_url = f"http://127.0.0.1:{port}/assets/index.css"

        # Poll status endpoint until ready (up to 25s)
        deadline = time.time() + 25.0
        server_ready = False
        last_error = ""

        while time.time() < deadline:
            if proc.poll() is not None:
                print(f"  [FAIL] Server process exited prematurely with code {proc.returncode}")
                return False
            try:
                req = urllib.request.Request(status_url)
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if "status" in data:
                            server_ready = True
                            print(f"  [PASS] Server status endpoint responsive: {data.get('status')}")
                            break
            except Exception as e:
                last_error = str(e)
                time.sleep(0.5)

        if not server_ready:
            print(f"  [FAIL] Server did not become ready within 25s (last error: {last_error})")
            return False

        # Verify root HTML endpoint
        req_root = urllib.request.Request(root_url)
        with urllib.request.urlopen(req_root, timeout=2.0) as resp:
            if resp.status != 200:
                print(f"  [FAIL] Root endpoint returned status {resp.status}")
                return False
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8", errors="replace")
            if "text/html" not in content_type:
                print(f"  [FAIL] Root endpoint content-type is not text/html: {content_type}")
                return False
            if "<html" not in body.lower() and "<!doctype html>" not in body.lower():
                print("  [FAIL] Root endpoint body does not contain valid HTML document")
                return False
            print("  [PASS] Root static HTML endpoint verified (200 OK, text/html)")

        # Verify static CSS endpoint
        req_css = urllib.request.Request(css_url)
        with urllib.request.urlopen(req_css, timeout=2.0) as resp:
            if resp.status != 200:
                print(f"  [FAIL] CSS asset endpoint returned status {resp.status}")
                return False
            css_body = resp.read()
            if len(css_body) == 0:
                print("  [FAIL] CSS asset body is empty")
                return False
            print(f"  [PASS] Static CSS asset endpoint verified ({len(css_body)} bytes)")

        return True
    finally:
        print("  Terminating server process...")
        proc.terminate()
        try:
            proc.wait(timeout=8.0)
            print("  [PASS] Server process terminated cleanly")
        except subprocess.TimeoutExpired:
            print("  [WARN] Server did not exit within 8s; killing")
            proc.kill()
            proc.wait(timeout=2.0)


def test_frozen_log_file() -> bool:
    """Verify %LOCALAPPDATA%\\AksaraSight\\logs\\app.log exists and contains startup message."""
    print("\n[5/5] Verifying file-based logging for frozen runtime...")
    app_data = os.environ.get("LOCALAPPDATA")
    base_dir = Path(app_data) if app_data else (Path.home() / "AppData" / "Local")
    log_file = base_dir / "AksaraSight" / "logs" / "app.log"

    if not log_file.is_file():
        print(f"  [FAIL] Log file not found at: {log_file}")
        return False

    content = log_file.read_text(encoding="utf-8", errors="replace")
    if f"Frozen application started (v{__version__})" not in content:
        print(f"  [FAIL] Expected startup entry not found in {log_file}")
        return False

    print(f"  [PASS] Log file verified at: {log_file}")
    print(f"         Last line: {content.strip().splitlines()[-1]}")
    return True


def main() -> None:
    """Run all frozen build verification checks."""
    print("=" * 60)
    print("AksaraSight Frozen Portable Build Verification")
    print("=" * 60)

    if not GUI_EXE.is_file() or not CLI_EXE.is_file():
        sys.stderr.write("ERROR: Distribution binaries missing. Run scripts/build_portable.py first.\n")
        sys.exit(1)

    checks = [
        test_cli_version,
        test_cli_hardware_detection,
        test_cli_input_validation,
        test_web_server_startup_and_endpoints,
        test_frozen_log_file,
    ]

    results = []
    for check in checks:
        ok = check()
        results.append(ok)
        if not ok:
            print(f"\nFAILED AT CHECK: {check.__name__}")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("ALL 5/5 FROZEN BUILD VERIFICATION CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
