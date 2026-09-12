"""Command Line Interface for OCR-LLM-Local."""

import argparse
from pathlib import Path
import sys
from typing import List, Optional, Sequence, Set

from config.settings import Settings, VALID_BACKENDS
from core.engine import OCREngine
from core.constants import SUPPORTED_EXTENSIONS
from core.formatter import save_artifacts
from core.models import JobConfig, JobStatus, OCRResult, OutputFormat


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="ocr-llm",
        description="Lightweight local OCR tool powered by OpenAI-compatible vision models.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to an input image/PDF file or directory of documents.",
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
        choices=["markdown", "json", "both"],
        default="markdown",
        help="Output format: 'markdown' (default), 'json', or 'both'.",
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

    input_path: Path = args.input

    # 1. Validate input existence (Fatal error -> Exit Code 1)
    if not input_path.exists():
        sys.stderr.write(f"Error: Input path does not exist: '{input_path}'\n")
        return 1

    # 2. Build Settings with CLI overrides and validate
    try:
        base_settings = Settings.from_env()
        settings = Settings(
            backend=args.backend or base_settings.backend,
            local_endpoint=args.endpoint or base_settings.local_endpoint,
            timeout=base_settings.timeout,
            max_retries=base_settings.max_retries,
            allow_remote=args.allow_remote or base_settings.allow_remote,
        )
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
    output_fmt = OutputFormat(args.format.lower())
    job_config = JobConfig(
        output_format=output_fmt,
        prompt_mode=args.prompt_mode,
        custom_prompt=args.prompt,
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
        file_list = [input_path.resolve()]

    # 5. Initialize Engine and process documents
    engine = OCREngine(settings=settings)
    results: List[OCRResult] = []
    total_files = len(file_list)
    used_stems: Set[str] = set()

    for idx, doc_path in enumerate(file_list, 1):
        if not args.quiet and total_files > 1:
            sys.stdout.write(f"[{idx}/{total_files}] Processing {doc_path.name}...\n")
            sys.stdout.flush()

        result = engine.process_document(doc_path, config=job_config)
        results.append(result)

        # Save to disk if -o is specified
        if args.output is not None:
            save_artifacts(result, job_config, output_dir=args.output, used_stems=used_stems)
            if not args.quiet and total_files > 1:
                status_label = result.status.value
                sys.stdout.write(f"[{idx}/{total_files}] {doc_path.name} -> {status_label} ({result.total_duration:.2f}s)\n")
                sys.stdout.flush()
        else:
            # Single-file stdout streaming mode
            if result.status == JobStatus.FAILED and not result.pages:
                sys.stderr.write(f"Processing failed: {result.error}\n")
            else:
                if output_fmt == OutputFormat.MARKDOWN:
                    sys.stdout.write(result.to_markdown())
                    if not result.to_markdown().endswith("\n"):
                        sys.stdout.write("\n")
                elif output_fmt == OutputFormat.JSON:
                    sys.stdout.write(result.to_json() + "\n")
                else:  # BOTH to stdout
                    sys.stdout.write(result.to_markdown())
                    sys.stdout.write("\n\n---\n\n")
                    sys.stdout.write(result.to_json() + "\n")
                sys.stdout.flush()

        # If processing was aborted due to backend offline, fail fast immediately
        if result.aborted:
            if not args.quiet:
                sys.stderr.write(f"Aborted: {result.error}\n")
            return 1

    # 6. Exit code calculation
    if any(r.aborted for r in results):
        return 1

    if all(r.status == JobStatus.SUCCESS for r in results):
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
