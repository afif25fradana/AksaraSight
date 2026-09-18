"""Command Line Interface for AksaraSight."""

import argparse
import dataclasses
from pathlib import Path
import sys
from typing import List, Optional, Sequence, Set

from config.settings import Settings, VALID_BACKENDS
from core.client import ClientError, ServerOfflineError
from core.engine import OCREngine
from core.constants import SUPPORTED_EXTENSIONS, __version__
from core.formatter import format_output, save_artifacts
from core.hardware import PINNED_LLAMA_BUILD, detect_hardware
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat
from core.runtime_manager import (
    get_installed_runtime_path,
    get_runtime_dir,
    is_runtime_installed,
)
from core.server_manager import ServerStatus, probe_server_health, resolve_base_url


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="AksaraSight-CLI",
        description="Lightweight local OCR tool powered by OpenAI-compatible vision models.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=None,
        help="Path to an input image/PDF file or directory of documents.",
    )
    parser.add_argument(
        "--detect-hardware",
        action="store_true",
        help="Detect system GPU/CPU hardware and recommend the optimal local inference runtime backend.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run a diagnostic health-check of the local OCR environment and print a report.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Directory to save output files. If omitted, outputs directly to stdout.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["markdown", "json", "both", "docx"],
        default="markdown",
        help="Output format: 'markdown' (default), 'json', 'both', or 'docx'.",
    )
    parser.add_argument(
        "-p",
        "--prompt-mode",
        choices=["text", "table", "formula"],
        default="text",
        help="Prompt preset mode: 'text' (default), 'table', or 'formula'.",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Custom prompt instruction override bypassing presets.",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively scan subdirectories when input is a folder.",
    )
    parser.add_argument(
        "--backend",
        choices=sorted(VALID_BACKENDS),
        default=None,
        help="Override local inference backend ('llama-cpp', 'ollama', 'vllm').",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="Override OpenAI-compatible base URL (e.g. 'http://localhost:8080/v1').",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Explicitly permit connecting to non-loopback / remote inference endpoints.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of pages to process per document.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=None,
        help="Rasterization DPI for PDF documents (default: 100).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress and status logs, emitting only raw output to stdout.",
    )
    return parser


def discover_files(input_dir: Path, recursive: bool = False) -> List[Path]:
    """Discover supported document files in a directory."""
    if recursive:
        candidates = input_dir.rglob("*")
    else:
        candidates = input_dir.glob("*")

    files = [
        p.resolve()
        for p in candidates
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    files.sort()
    return files


def run_doctor(args: argparse.Namespace) -> int:
    """Execute a comprehensive diagnostic health-check and print a human-readable report.

    Verifies configuration, hardware detection, runtime installation (managed or custom),
    server reachability, and multimodal vision processing capability.

    Returns:
        int: 0 if all diagnostic checks pass, 1 if any check fails.
    """
    lines = [
        "==================================================",
        "           AKSARASIGHT DIAGNOSTIC REPORT          ",
        "==================================================",
    ]
    failed_checks = 0
    remediations: List[str] = []

    # 1. Configuration
    lines.append("1. Configuration")
    config_ok = False
    settings: Optional[Settings] = None
    try:
        base_settings = Settings.from_env()
        overrides = {}
        if args.backend:
            overrides["backend"] = args.backend
        if args.endpoint:
            overrides["local_endpoint"] = args.endpoint
        if args.allow_remote:
            overrides["allow_remote"] = True
        settings = dataclasses.replace(base_settings, **overrides)

        loopback_str = "yes" if settings.is_loopback else "no (WARNING: non-loopback)"
        lines.append(f"   [PASS] Backend:             {settings.backend}")
        if settings.runtime_mode == "managed":
            lines.append(f"   [PASS] Runtime Mode:        managed (target: {settings.managed_backend_override})")
        else:
            lines.append("   [PASS] Runtime Mode:        custom")
        lines.append(f"   [PASS] Endpoint:            {settings.local_endpoint} (loopback: {loopback_str})")
        config_ok = True
    except ValueError as exc:
        lines.append(f"   [FAIL] Configuration:       Invalid settings: {exc}")
        failed_checks += 1
        remediations.append("Fix invalid configuration in .env or provide valid CLI arguments.")

    # 2. Hardware Detection
    lines.append("\n2. Hardware Detection")
    profile = detect_hardware()
    cpu_label = profile.cpu_name or "Unknown"
    gpu_label = profile.gpu_name or "None (CPU fallback)"
    if profile.vram_mb:
        gpu_label += f" ({profile.vram_mb} MB)"
    lines.append(f"   [PASS] CPU:                 {cpu_label}")
    lines.append(f"   [PASS] Primary GPU:         {gpu_label}")
    if profile.cuda_available:
        if profile.cuda_supported:
            driver_str = f" (driver: {profile.cuda_driver_version})" if profile.cuda_driver_version else ""
            lines.append(f"   [PASS] Acceleration:        CUDA 12.4 Compatible{driver_str}")
        else:
            reason = f": {profile.cuda_incompatibility_reason}" if profile.cuda_incompatibility_reason else ""
            lines.append(f"   [WARN] Acceleration:        CUDA Incompatible{reason}")
    elif profile.vulkan_available:
        dev_name = f" ({profile.vulkan_device_name})" if profile.vulkan_device_name else ""
        lines.append(f"   [PASS] Acceleration:        Vulkan Compatible{dev_name}")
    else:
        lines.append("   [INFO] Acceleration:        CPU inference only")

    lines.append(f"   [PASS] Recommended Backend: {profile.recommended_backend.upper()}")

    # 3. Runtime Installation (branching on runtime_mode)
    if not config_ok or settings is None:
        lines.append("\n3. Runtime Installation")
        lines.append("   [SKIP] Runtime Check:       SKIPPED (Configuration error)")
    elif settings.runtime_mode == "custom":
        lines.append("\n3. Runtime Installation (Custom Path)")
        custom_path_str = settings.effective_llama_server_path
        if custom_path_str:
            custom_path = Path(custom_path_str)
            if custom_path.is_file():
                lines.append("   [PASS] Custom Binary:       FOUND")
                lines.append(f"          Path:                {custom_path.resolve()}")
            else:
                lines.append("   [FAIL] Custom Binary:       NOT FOUND")
                lines.append(f"          Path:                {custom_path_str}")
                failed_checks += 1
                remediations.append(f"Verify the custom binary path exists: '{custom_path_str}'.")
        else:
            lines.append("   [FAIL] Custom Binary:       NOT CONFIGURED")
            lines.append("          Path:                None")
            failed_checks += 1
            remediations.append("Configure OCR_LLAMA_SERVER_PATH in .env or switch to managed runtime mode.")
    else:  # settings.runtime_mode == "managed"
        lines.append("\n3. Runtime Installation (Managed Mode)")
        target_backend = settings.managed_backend_override
        if target_backend == "auto":
            target_backend = profile.recommended_backend

        tag = PINNED_LLAMA_BUILD
        installed = is_runtime_installed(tag=tag, backend=target_backend)
        installed_path = get_installed_runtime_path(tag=tag, backend=target_backend)

        if installed and installed_path is not None:
            lines.append(f"   [PASS] Managed Runtime:     {tag}-{target_backend} (INSTALLED)")
            lines.append(f"          Executable:          {installed_path}")
        else:
            expected_dir = get_runtime_dir(tag, target_backend)
            exe_name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
            expected_path = expected_dir / exe_name
            lines.append(f"   [FAIL] Managed Runtime:     {tag}-{target_backend} (NOT INSTALLED)")
            lines.append(f"          Executable:          {expected_path}")
            failed_checks += 1
            remediations.append(
                f"Install the managed runtime '{tag}-{target_backend}' via GUI Settings or download to '{expected_dir}'."
            )

    # 4. Server Reachability
    lines.append("\n4. Server Reachability")
    server_ready = False
    if not config_ok or settings is None:
        lines.append("   [SKIP] Endpoint Health:     SKIPPED (Configuration error)")
    else:
        health_status, health_msg = probe_server_health(settings.local_endpoint, timeout=1.5)
        base_url = resolve_base_url(settings.local_endpoint)
        health_url = f"{base_url}/health"

        if health_status == ServerStatus.READY:
            lines.append(f"   [PASS] Endpoint Health:     READY ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            server_ready = True
        elif health_status == ServerStatus.STARTING:
            lines.append(f"   [WARN] Endpoint Health:     STARTING ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            failed_checks += 1
            remediations.append("Server is starting or loading model weights; wait a moment and re-run --doctor.")
        elif health_status == ServerStatus.OFFLINE:
            lines.append(f"   [FAIL] Endpoint Health:     OFFLINE ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            failed_checks += 1
            remediations.append("Start the backend server via GUI or run 'llama-server' before processing documents.")
        else:  # ServerStatus.ERROR
            lines.append(f"   [FAIL] Endpoint Health:     ERROR ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            failed_checks += 1
            remediations.append(f"Server returned an error during health check: {health_msg}")

    # 5. Multimodal Vision Probe
    lines.append("\n5. Multimodal Vision Probe")
    if not config_ok or settings is None or not server_ready:
        skip_reason = "Configuration error" if not config_ok else "Server is not ready"
        lines.append(f"   [SKIP] 1x1 Image Test:      SKIPPED ({skip_reason})")
    else:
        engine = OCREngine(settings=settings)
        try:
            engine.verify_backend(force=True)
            lines.append("   [PASS] 1x1 Image Test:      VERIFIED (Vision projector active, inference operational)")
        except ServerOfflineError as exc:
            lines.append(f"   [FAIL] 1x1 Image Test:      FAILED (Server offline: {exc})")
            failed_checks += 1
            remediations.append("Server became unreachable during multimodal vision probe.")
        except ClientError as exc:
            lines.append(f"   [FAIL] 1x1 Image Test:      FAILED ({exc})")
            failed_checks += 1
            remediations.append("Ensure the backend was launched with multimodal vision projector support (--mmproj).")
        except Exception as exc:
            lines.append(f"   [FAIL] 1x1 Image Test:      FAILED ({exc})")
            failed_checks += 1
            remediations.append(f"Unexpected probe error: {exc}")

    # Final Result & Summary
    lines.append("==================================================")
    total_checks = 5
    if failed_checks == 0:
        lines.append(f"STATUS: HEALTHY - All checks passed ({total_checks}/{total_checks}). Ready for OCR processing.")
        exit_code = 0
    else:
        s_plural = "s" if failed_checks > 1 else ""
        lines.append(f"STATUS: UNHEALTHY - {failed_checks} check{s_plural} failed.")
        if remediations:
            lines.append("Remediation:")
            for item in remediations:
                lines.append(f"  - {item}")
        exit_code = 1

    sys.stdout.write("\n".join(lines) + "\n")
    return exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Execute the CLI application.

    Returns:
        int: Exit code:
            - 0: All documents processed successfully.
            - 1: Fatal configuration, input, or server-offline error.
            - 2: Partial failure (one or more documents/pages failed).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Handle --detect-hardware standalone diagnostic action
    if args.detect_hardware:
        profile = detect_hardware()
        sys.stdout.write(profile.format_summary() + "\n")
        return 0

    # Handle --doctor standalone diagnostic health-check
    if args.doctor:
        return run_doctor(args)

    # Ensure input argument was supplied
    if not args.input:
        parser.print_usage(sys.stderr)
        sys.stderr.write("AksaraSight-CLI: error: the following arguments are required: input\n")
        return 1

    input_path: Path = args.input

    # 1. Validate input existence (Fatal error -> Exit Code 1)
    if not input_path.exists():
        sys.stderr.write(f"Error: Input path does not exist: '{input_path}'\n")
        return 1

    # 2. Build Settings with CLI overrides and validate
    try:
        base_settings = Settings.from_env()
        overrides = {}
        if args.backend:
            overrides["backend"] = args.backend
        if args.endpoint:
            overrides["local_endpoint"] = args.endpoint
        if args.allow_remote:
            overrides["allow_remote"] = True
        settings = dataclasses.replace(base_settings, **overrides)
    except ValueError as exc:
        sys.stderr.write(f"Configuration error: {exc}\n")
        return 1

    # Emit prominent warning if non-loopback endpoint is in use
    if not settings.is_loopback:
        sys.stderr.write(
            f"WARNING: Backend endpoint is non-loopback — document data will leave this machine: "
            f"'{settings.local_endpoint}'\n"
        )

    # 3. Build JobConfig
    if args.max_pages is not None and args.max_pages <= 0:
        sys.stderr.write("Error: --max-pages must be a positive integer.\n")
        return 1

    if args.dpi is not None and args.dpi <= 0:
        sys.stderr.write("Error: --dpi must be a positive integer.\n")
        return 1

    output_fmt = OutputFormat(args.format.lower())
    job_config = JobConfig(
        output_format=output_fmt,
        prompt_mode=args.prompt_mode,
        custom_prompt=args.prompt,
        max_pages=args.max_pages if args.max_pages is not None else settings.max_pages,
        dpi=args.dpi or settings.dpi,
        max_image_dimension=settings.max_image_dimension,
    )

    # 4. Resolve files to process
    if input_path.is_dir():
        if args.output is None:
            sys.stderr.write("Error: -o/--output directory is required when input is a directory.\n")
            return 1
        file_list = discover_files(input_path, recursive=args.recursive)
        if not file_list:
            sys.stderr.write(f"Error: No supported document files found in '{input_path}'.\n")
            return 1
    else:
        if output_fmt == OutputFormat.DOCX and args.output is None and sys.stdout.isatty():
            sys.stderr.write("Error: Cannot write binary DOCX output to a terminal. Specify -o/--output or redirect stdout.\n")
            return 1
        file_list = [input_path.resolve()]

    # 5. Initialize Engine and process documents (streaming mode to prevent unbounded memory growth)
    engine = OCREngine(settings=settings)

    # Pre-flight startup self-test before processing the first document
    try:
        engine.verify_backend()
    except Exception as probe_exc:
        sys.stderr.write(f"Error: {probe_exc}\n")
        return 1

    has_aborted = False
    all_success = True
    total_files = len(file_list)
    used_stems: Set[str] = set()

    for idx, doc_path in enumerate(file_list, 1):
        if not args.quiet and total_files > 1:
            sys.stdout.write(f"[{idx}/{total_files}] Processing {doc_path.name}...\n")
            sys.stdout.flush()

        result = engine.process_document(doc_path, config=job_config)
        if result.aborted:
            has_aborted = True
        if result.status != JobStatus.SUCCESS:
            all_success = False

        # Save to disk if -o is specified
        if args.output is not None:
            save_artifacts(
                result,
                job_config,
                output_dir=args.output,
                used_stems=used_stems,
                base_dir=input_path if input_path.is_dir() else None,
            )
            if not args.quiet and total_files > 1:
                status_label = result.status.value
                sys.stdout.write(f"[{idx}/{total_files}] {doc_path.name} -> {status_label} ({result.total_duration:.2f}s)\n")
                sys.stdout.flush()
        else:
            # Single-file stdout streaming mode
            if result.status == JobStatus.FAILED and not result.pages:
                sys.stderr.write(f"Processing failed: {result.error}\n")
            else:
                formatted = format_output(result, output_fmt, sanitize_path=True)
                if output_fmt == OutputFormat.MARKDOWN:
                    md = formatted["markdown"]
                    sys.stdout.write(md)
                    if not md.endswith("\n"):
                        sys.stdout.write("\n")
                elif output_fmt == OutputFormat.JSON:
                    sys.stdout.write(formatted["json"] + "\n")
                elif output_fmt == OutputFormat.DOCX:
                    if sys.stdout.isatty():
                        sys.stderr.write("Error: Cannot write binary DOCX output to a terminal. Specify -o/--output or redirect stdout.\n")
                        return 1
                    raw_docx = formatted["docx"]
                    if hasattr(sys.stdout, "buffer"):
                        sys.stdout.buffer.write(raw_docx)
                    else:
                        sys.stdout.write(raw_docx)  # type: ignore[arg-type]
                else:  # BOTH to stdout
                    sys.stdout.write(formatted["markdown"])
                    sys.stdout.write("\n\n---\n\n")
                    sys.stdout.write(formatted["json"] + "\n")
                sys.stdout.flush()

        # If processing was aborted due to backend offline, fail fast immediately
        if result.aborted:
            if not args.quiet:
                sys.stderr.write(f"Aborted: {result.error}\n")
            return 1

    # 6. Exit code calculation
    if has_aborted:
        return 1

    if all_success:
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
