"""Command Line Interface for AksaraSight."""

import argparse
import dataclasses
from pathlib import Path
import sys
from typing import List, Optional, Sequence, Set

from config.settings import Settings, VALID_BACKENDS
from core.constants import SUPPORTED_EXTENSIONS, __version__
from core.diagnostics import run_diagnostics
from core.engine import OCREngine
from core.formatter import format_output, save_artifacts
from core.hardware import (
    detect_hardware,
    get_cached_hardware_profile,
    start_hardware_prewarm,
)
from core.models import JobConfig, JobStatus, OutputFormat
from core.runtime_manager import (
    get_installed_runtime_path,
    is_runtime_installed,
)
from core.server_manager import probe_server_health


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="AksaraSight-CLI",
        description="Lightweight local OCR tool using OpenAI-compatible vision models.",
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
    report = run_diagnostics(
        backend=args.backend,
        endpoint=args.endpoint,
        allow_remote=args.allow_remote,
        hardware_detector=detect_hardware,
        runtime_checker=is_runtime_installed,
        runtime_path_getter=get_installed_runtime_path,
        server_prober=probe_server_health,
        engine_factory=OCREngine,
    )
    sys.stdout.write(report.format_text() + "\n")
    return report.exit_code


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

    if not input_path.exists():
        sys.stderr.write(f"Error: Input path does not exist: '{input_path}'\n")
        return 1

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
            f"WARNING: Backend endpoint is non-loopback; document data will leave this machine: "
            f"'{settings.local_endpoint}'\n"
        )

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

    # Pre-warm hardware detection only when proceeding with document processing against loopback backend
    if settings.is_loopback:
        start_hardware_prewarm()

    engine = OCREngine(settings=settings)

    # Pre-flight startup self-test before processing the first document
    try:
        engine.verify_backend()
    except Exception as probe_exc:
        sys.stderr.write(f"Error: {probe_exc}\n")
        return 1

    if settings.is_loopback:
        profile = get_cached_hardware_profile(blocking=True)
        if (
            profile is not None
            and profile.cuda_available
            and profile.vram_mb is not None
            and profile.vram_mb < 2200
        ):
            sys.stderr.write(
                f"WARNING: Detected {profile.vram_mb} MB VRAM on '{profile.gpu_name or 'CUDA device'}', "
                f"below recommended ~2.2 GB for GLM-OCR (-c 8192). Server may encounter CUDA out-of-memory errors.\n"
            )

    has_aborted = False
    all_success = True
    total_files = len(file_list)
    used_stems: Set[str] = set()

    for idx, doc_path in enumerate(file_list, 1):
        if not args.quiet and total_files > 1:
            sys.stdout.write(f"[{idx}/{total_files}] Processing {doc_path.name}...\n")
            sys.stdout.flush()

        try:
            result = engine.process_document(doc_path, config=job_config)
        except Exception as exc:
            all_success = False
            sys.stderr.write(f"Error processing {doc_path.name}: {exc}\n")
            sys.stderr.flush()
            continue

        if result.aborted:
            has_aborted = True
        if result.status != JobStatus.SUCCESS:
            all_success = False

        # Save to disk if -o is specified; format and emit to stdout otherwise.
        # A failure here (e.g. corrupt markdown AST, disk full on this file only,
        # NTFS name too long) is document-specific, not systemic — isolate it so
        # the remaining batch documents are still exported.
        # Note: KeyboardInterrupt is a BaseException, not Exception, so it is
        # never caught here and always propagates immediately.
        try:
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
                        raw_docx = formatted["docx"]
                        if hasattr(sys.stdout, "buffer"):
                            sys.stdout.buffer.write(raw_docx)
                        else:
                            sys.stderr.write("Error: stdout does not support binary output. Specify -o/--output to write DOCX to disk.\n")
                            return 1
                    else:  # BOTH to stdout
                        sys.stdout.write(formatted["markdown"])
                        sys.stdout.write("\n\n---\n\n")
                        sys.stdout.write(formatted["json"] + "\n")
                    sys.stdout.flush()
        except Exception as export_exc:
            all_success = False
            sys.stderr.write(f"Error saving output for {doc_path.name}: {export_exc}\n")
            sys.stderr.flush()

        # If processing was aborted due to backend offline, fail fast immediately
        if result.aborted:
            if not args.quiet:
                sys.stderr.write(f"Aborted: {result.error}\n")
            return 1

    if has_aborted:
        raise RuntimeError("unreachable: aborted batch jobs must fail fast and return early")

    if all_success:
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
