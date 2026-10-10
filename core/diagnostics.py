"""Diagnostic health check engine and reporting model for AksaraSight."""

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import sys
from typing import Callable, List, Optional, Tuple

from config.settings import Settings
from core.client import ClientError, ServerOfflineError
from core.engine import OCREngine
from core.hardware import (
    MIN_RECOMMENDED_VRAM_MB,
    PINNED_LLAMA_BUILD,
    HardwareProfile,
    detect_hardware as default_detect_hardware,
)
from core.runtime_manager import (
    get_installed_runtime_path as default_get_installed_runtime_path,
    get_runtime_dir,
    is_runtime_installed as default_is_runtime_installed,
)
from core.server_manager import (
    ServerStatus,
    probe_server_health as default_probe_server_health,
    resolve_base_url,
)


class DiagnosticStatus(str, Enum):
    """Status outcomes for individual diagnostic checks."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"
    SKIP = "SKIP"


@dataclass
class DiagnosticCheck:
    """Individual diagnostic check result and metadata."""

    name: str
    status: DiagnosticStatus
    message: str
    details: Optional[str] = None


@dataclass
class DiagnosticReport:
    """Complete diagnostic health check report."""

    checks: List[DiagnosticCheck] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    remediations: List[str] = field(default_factory=list)
    failed_checks: int = 0
    exit_code: int = 0

    def format_text(self) -> str:
        """Format the diagnostic report as a human-readable CLI string."""
        return "\n".join(self.lines)


def run_diagnostics(
    settings: Optional[Settings] = None,
    backend: Optional[str] = None,
    endpoint: Optional[str] = None,
    allow_remote: bool = False,
    *,
    hardware_detector: Optional[Callable[[], HardwareProfile]] = None,
    runtime_checker: Optional[Callable[..., bool]] = None,
    runtime_path_getter: Optional[Callable[..., Optional[Path]]] = None,
    server_prober: Optional[Callable[..., Tuple[ServerStatus, str]]] = None,
    engine_factory: Optional[Callable[..., OCREngine]] = None,
) -> DiagnosticReport:
    """Execute a comprehensive diagnostic health check and return a DiagnosticReport.

    Verifies configuration, hardware detection, runtime installation (managed or custom),
    server reachability, and multimodal vision processing capability.

    Args:
        settings: Optional pre-constructed Settings instance. If None, Settings.from_env() is used.
        backend: Optional CLI/runtime backend override.
        endpoint: Optional local endpoint URL override.
        allow_remote: Whether non-loopback endpoints are allowed.
        hardware_detector: Callable returning HardwareProfile (defaults to detect_hardware).
        runtime_checker: Callable checking runtime installation (defaults to is_runtime_installed).
        runtime_path_getter: Callable returning runtime Path (defaults to get_installed_runtime_path).
        server_prober: Callable probing server health (defaults to probe_server_health).
        engine_factory: Callable creating OCREngine (defaults to OCREngine).

    Returns:
        DiagnosticReport containing checks, formatted lines, remediations, and exit_code.
    """
    detect_hw = hardware_detector or default_detect_hardware
    check_runtime = runtime_checker or default_is_runtime_installed
    get_runtime_path = runtime_path_getter or default_get_installed_runtime_path
    probe_server = server_prober or default_probe_server_health
    make_engine = engine_factory or OCREngine

    lines: List[str] = [
        "==================================================",
        "           AKSARASIGHT DIAGNOSTIC REPORT          ",
        "==================================================",
    ]
    failed_checks = 0
    remediations: List[str] = []
    checks: List[DiagnosticCheck] = []

    # 1. Configuration
    lines.append("1. Configuration")
    config_ok = False
    effective_settings: Optional[Settings] = None
    try:
        base_settings = settings or Settings.from_env()
        overrides = {}
        if backend:
            overrides["backend"] = backend
        if endpoint:
            overrides["local_endpoint"] = endpoint
        if allow_remote:
            overrides["allow_remote"] = True
        effective_settings = (
            dataclasses.replace(base_settings, **overrides) if overrides else base_settings
        )

        loopback_str = "yes" if effective_settings.is_loopback else "no (WARNING: non-loopback)"
        lines.append(f"   [PASS] Backend:             {effective_settings.backend}")
        if effective_settings.runtime_mode == "managed":
            lines.append(
                f"   [PASS] Runtime Mode:        managed (target: {effective_settings.managed_backend_override})"
            )
        else:
            lines.append("   [PASS] Runtime Mode:        custom")
        lines.append(
            f"   [PASS] Endpoint:            {effective_settings.local_endpoint} (loopback: {loopback_str})"
        )
        checks.append(
            DiagnosticCheck(
                name="Configuration",
                status=DiagnosticStatus.PASS,
                message=f"Backend: {effective_settings.backend}, Mode: {effective_settings.runtime_mode}",
            )
        )
        config_ok = True
    except ValueError as exc:
        lines.append(f"   [FAIL] Configuration:       Invalid settings: {exc}")
        failed_checks += 1
        remediations.append("Fix invalid configuration in .env or provide valid CLI arguments.")
        checks.append(
            DiagnosticCheck(
                name="Configuration",
                status=DiagnosticStatus.FAIL,
                message=f"Invalid settings: {exc}",
            )
        )

    # 2. Hardware Detection
    lines.append("\n2. Hardware Detection")
    profile = detect_hw()
    cpu_label = profile.cpu_name or "Unknown"
    gpu_label = profile.gpu_name or "None (CPU fallback)"
    if profile.vram_mb:
        gpu_label += f" ({profile.vram_mb} MB)"
    lines.append(f"   [PASS] CPU:                 {cpu_label}")
    lines.append(f"   [PASS] Primary GPU:         {gpu_label}")
    if profile.cuda_available:
        if profile.cuda_supported:
            driver_str = (
                f" (driver: {profile.cuda_driver_version})" if profile.cuda_driver_version else ""
            )
            lines.append(f"   [PASS] Acceleration:        CUDA 12.4 Compatible{driver_str}")
            checks.append(
                DiagnosticCheck(
                    name="Acceleration",
                    status=DiagnosticStatus.PASS,
                    message=f"CUDA 12.4 Compatible{driver_str}",
                )
            )
        else:
            reason = (
                f": {profile.cuda_incompatibility_reason}"
                if profile.cuda_incompatibility_reason
                else ""
            )
            lines.append(f"   [WARN] Acceleration:        CUDA Incompatible{reason}")
            checks.append(
                DiagnosticCheck(
                    name="Acceleration",
                    status=DiagnosticStatus.WARN,
                    message=f"CUDA Incompatible{reason}",
                )
            )
    elif profile.vulkan_available:
        dev_name = f" ({profile.vulkan_device_name})" if profile.vulkan_device_name else ""
        lines.append(f"   [PASS] Acceleration:        Vulkan Compatible{dev_name}")
        checks.append(
            DiagnosticCheck(
                name="Acceleration",
                status=DiagnosticStatus.PASS,
                message=f"Vulkan Compatible{dev_name}",
            )
        )
    else:
        lines.append("   [INFO] Acceleration:        CPU inference only")
        checks.append(
            DiagnosticCheck(
                name="Acceleration",
                status=DiagnosticStatus.INFO,
                message="CPU inference only",
            )
        )

    if profile.vram_mb is not None and profile.vram_mb < MIN_RECOMMENDED_VRAM_MB:
        lines.append(
            f"   [WARN] VRAM:                {profile.vram_mb} MB detected (below recommended minimum of "
            f"{MIN_RECOMMENDED_VRAM_MB} MB). Full GPU offload may not fit; expect partial CPU fallback."
        )

    lines.append(f"   [PASS] Recommended Backend: {profile.recommended_backend.upper()}")

    # 3. Runtime Installation
    if not config_ok or effective_settings is None:
        lines.append("\n3. Runtime Installation")
        lines.append("   [SKIP] Runtime Check:       SKIPPED (Configuration error)")
        checks.append(
            DiagnosticCheck(
                name="Runtime Check",
                status=DiagnosticStatus.SKIP,
                message="SKIPPED (Configuration error)",
            )
        )
    elif effective_settings.runtime_mode == "custom":
        lines.append("\n3. Runtime Installation (Custom Path)")
        custom_path_str = effective_settings.effective_llama_server_path
        if custom_path_str:
            custom_path = Path(custom_path_str)
            if custom_path.is_file():
                lines.append("   [PASS] Custom Binary:       FOUND")
                lines.append(f"          Path:                {custom_path.resolve()}")
                checks.append(
                    DiagnosticCheck(
                        name="Custom Binary",
                        status=DiagnosticStatus.PASS,
                        message="FOUND",
                        details=str(custom_path.resolve()),
                    )
                )
            else:
                lines.append("   [FAIL] Custom Binary:       NOT FOUND")
                lines.append(f"          Path:                {custom_path_str}")
                failed_checks += 1
                remediations.append(f"Verify the custom binary path exists: '{custom_path_str}'.")
                checks.append(
                    DiagnosticCheck(
                        name="Custom Binary",
                        status=DiagnosticStatus.FAIL,
                        message="NOT FOUND",
                        details=custom_path_str,
                    )
                )
        else:
            lines.append("   [FAIL] Custom Binary:       NOT CONFIGURED")
            lines.append("          Path:                None")
            failed_checks += 1
            remediations.append(
                "Configure OCR_LLAMA_SERVER_PATH in .env or switch to managed runtime mode."
            )
            checks.append(
                DiagnosticCheck(
                    name="Custom Binary",
                    status=DiagnosticStatus.FAIL,
                    message="NOT CONFIGURED",
                    details="None",
                )
            )
    else:  # effective_settings.runtime_mode == "managed"
        lines.append("\n3. Runtime Installation (Managed Mode)")
        target_backend = effective_settings.managed_backend_override
        if target_backend == "auto":
            target_backend = profile.recommended_backend

        tag = PINNED_LLAMA_BUILD
        installed = check_runtime(tag=tag, backend=target_backend)
        installed_path = get_runtime_path(tag=tag, backend=target_backend)

        if installed and installed_path is not None:
            lines.append(f"   [PASS] Managed Runtime:     {tag}-{target_backend} (INSTALLED)")
            lines.append(f"          Executable:          {installed_path}")
            checks.append(
                DiagnosticCheck(
                    name="Managed Runtime",
                    status=DiagnosticStatus.PASS,
                    message=f"{tag}-{target_backend} (INSTALLED)",
                    details=str(installed_path),
                )
            )
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
            checks.append(
                DiagnosticCheck(
                    name="Managed Runtime",
                    status=DiagnosticStatus.FAIL,
                    message=f"{tag}-{target_backend} (NOT INSTALLED)",
                    details=str(expected_path),
                )
            )

    # 4. Server Reachability
    lines.append("\n4. Server Reachability")
    server_ready = False
    if not config_ok or effective_settings is None:
        lines.append("   [SKIP] Endpoint Health:     SKIPPED (Configuration error)")
        checks.append(
            DiagnosticCheck(
                name="Endpoint Health",
                status=DiagnosticStatus.SKIP,
                message="SKIPPED (Configuration error)",
            )
        )
    else:
        health_status, health_msg = probe_server(effective_settings.local_endpoint, timeout=1.5)
        base_url = resolve_base_url(effective_settings.local_endpoint)
        health_url = f"{base_url}/health"

        if health_status == ServerStatus.READY:
            lines.append(f"   [PASS] Endpoint Health:     READY ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            server_ready = True
            checks.append(
                DiagnosticCheck(
                    name="Endpoint Health",
                    status=DiagnosticStatus.PASS,
                    message=f"READY ({health_url})",
                    details=health_msg,
                )
            )
        elif health_status == ServerStatus.STARTING:
            lines.append(f"   [WARN] Endpoint Health:     STARTING ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            failed_checks += 1
            remediations.append(
                "Server is starting or loading model weights; wait a moment and re-run --doctor."
            )
            checks.append(
                DiagnosticCheck(
                    name="Endpoint Health",
                    status=DiagnosticStatus.WARN,
                    message=f"STARTING ({health_url})",
                    details=health_msg,
                )
            )
        elif health_status == ServerStatus.OFFLINE:
            lines.append(f"   [FAIL] Endpoint Health:     OFFLINE ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            failed_checks += 1
            remediations.append(
                "Start the backend server via GUI or run 'llama-server' before processing documents."
            )
            checks.append(
                DiagnosticCheck(
                    name="Endpoint Health",
                    status=DiagnosticStatus.FAIL,
                    message=f"OFFLINE ({health_url})",
                    details=health_msg,
                )
            )
        else:  # ServerStatus.ERROR
            lines.append(f"   [FAIL] Endpoint Health:     ERROR ({health_url})")
            lines.append(f"          Details:             {health_msg}")
            failed_checks += 1
            remediations.append(f"Server returned an error during health check: {health_msg}")
            checks.append(
                DiagnosticCheck(
                    name="Endpoint Health",
                    status=DiagnosticStatus.FAIL,
                    message=f"ERROR ({health_url})",
                    details=health_msg,
                )
            )

    # 5. Multimodal Vision Probe
    lines.append("\n5. Multimodal Vision Probe")
    if not config_ok or effective_settings is None or not server_ready:
        skip_reason = "Configuration error" if not config_ok else "Server is not ready"
        lines.append(f"   [SKIP] 1x1 Image Test:      SKIPPED ({skip_reason})")
        checks.append(
            DiagnosticCheck(
                name="1x1 Image Test",
                status=DiagnosticStatus.SKIP,
                message=f"SKIPPED ({skip_reason})",
            )
        )
    else:
        engine = make_engine(settings=effective_settings)
        try:
            engine.verify_backend(force=True)
            lines.append(
                "   [PASS] 1x1 Image Test:      VERIFIED (Vision projector active, inference operational)"
            )
            checks.append(
                DiagnosticCheck(
                    name="1x1 Image Test",
                    status=DiagnosticStatus.PASS,
                    message="VERIFIED (Vision projector active, inference operational)",
                )
            )
        except ServerOfflineError as exc:
            lines.append(f"   [FAIL] 1x1 Image Test:      FAILED (Server offline: {exc})")
            failed_checks += 1
            remediations.append("Server became unreachable during multimodal vision probe.")
            checks.append(
                DiagnosticCheck(
                    name="1x1 Image Test",
                    status=DiagnosticStatus.FAIL,
                    message=f"FAILED (Server offline: {exc})",
                )
            )
        except ClientError as exc:
            lines.append(f"   [FAIL] 1x1 Image Test:      FAILED ({exc})")
            failed_checks += 1
            remediations.append(
                "Ensure the backend was launched with multimodal vision projector support (--mmproj)."
            )
            checks.append(
                DiagnosticCheck(
                    name="1x1 Image Test",
                    status=DiagnosticStatus.FAIL,
                    message=f"FAILED ({exc})",
                )
            )
        except Exception as exc:
            lines.append(f"   [FAIL] 1x1 Image Test:      FAILED ({exc})")
            failed_checks += 1
            remediations.append(f"Unexpected probe error: {exc}")
            checks.append(
                DiagnosticCheck(
                    name="1x1 Image Test",
                    status=DiagnosticStatus.FAIL,
                    message=f"FAILED ({exc})",
                )
            )

    # Final Result & Summary
    lines.append("==================================================")
    total_checks = 5
    if failed_checks == 0:
        lines.append(
            f"STATUS: HEALTHY - All checks passed ({total_checks}/{total_checks}). Ready for OCR processing."
        )
        exit_code = 0
    else:
        s_plural = "s" if failed_checks > 1 else ""
        lines.append(f"STATUS: UNHEALTHY - {failed_checks} check{s_plural} failed.")
        if remediations:
            lines.append("Remediation:")
            for item in remediations:
                lines.append(f"  - {item}")
        exit_code = 1

    return DiagnosticReport(
        checks=checks,
        lines=lines,
        remediations=remediations,
        failed_checks=failed_checks,
        exit_code=exit_code,
    )
