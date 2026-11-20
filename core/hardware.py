"""Hardware capability detection and runtime recommendation engine.

Inspects local GPU and CPU capabilities to recommend the optimal
local inference backend (CUDA -> Vulkan -> CPU) with strict driver
version compatibility validation, zero network calls, and zero external dependencies.
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Pinned llama.cpp build known to work with PaddleOCR-VL-1.6-GGUF
PINNED_LLAMA_BUILD = "b11361"

# CUDA 12.4 driver thresholds on Windows:
# - Minimum display driver version: 550.54
# - Minimum CUDA driver API version: 12040 (cuDriverGetVersion)
MIN_CUDA_DRIVER_VERSION: Tuple[int, int] = (550, 54)
MIN_CUDA_DRIVER_API_VERSION: int = 12040

# Minimum recommended VRAM for PaddleOCR-VL-1.6 (requires ~3.0 GB under -c 8192 --parallel 1)
MIN_RECOMMENDED_VRAM_MB: int = 3000


@dataclass(frozen=True)
class HardwareProfile:
    """Snapshot representation of system hardware and runtime recommendations.

    Attributes:
        gpu_name: Detected primary GPU model name (or None if CPU-only).
        vram_mb: Dedicated GPU video memory in megabytes (if discoverable).
        cuda_available: Whether an NVIDIA GPU with driver support was detected.
        cuda_driver_version: Raw NVIDIA display driver version string (e.g. '551.76').
        cuda_driver_api_version: CUDA driver API version integer from cuDriverGetVersion (e.g. 12040).
        cuda_supported: True if driver version satisfies minimum requirement for target CUDA build.
        cuda_incompatibility_reason: Explanation if CUDA hardware is present but driver is incompatible.
        vulkan_available: Whether a Vulkan 1.2+ capable physical GPU device was detected.
        vulkan_device_name: Name of the active Vulkan physical device.
        cpu_name: Processor architecture and model descriptor.
        recommended_backend: Recommended runtime backend identifier ('cuda', 'vulkan', 'cpu').
        details: Concise human-readable explanation of the recommendation.
    """

    gpu_name: Optional[str] = None
    vram_mb: Optional[int] = None
    cuda_available: bool = False
    cuda_driver_version: Optional[str] = None
    cuda_driver_api_version: Optional[int] = None
    cuda_supported: bool = False
    cuda_incompatibility_reason: Optional[str] = None
    vulkan_available: bool = False
    vulkan_device_name: Optional[str] = None
    cpu_name: str = ""
    recommended_backend: str = "cpu"
    details: str = ""

    def format_summary(self) -> str:
        """Render a formatted, scannable terminal diagnostic report."""
        lines = [
            "==================================================",
            "          SYSTEM HARDWARE DETECTION REPORT         ",
            "==================================================",
            f"CPU:                  {self.cpu_name or 'Unknown'}",
            f"Primary GPU:          {self.gpu_name or 'None (CPU fallback)'}",
        ]
        if self.vram_mb:
            lines.append(f"Dedicated VRAM:       {self.vram_mb} MB ({self.vram_mb / 1024:.1f} GB)")
            if self.vram_mb < MIN_RECOMMENDED_VRAM_MB:
                lines.append(
                    f"  [WARN] Detected VRAM ({self.vram_mb} MB) is below the recommended minimum "
                    f"({MIN_RECOMMENDED_VRAM_MB} MB). Full GPU offload may not fit; "
                    "expect partial CPU fallback and slower inference."
                )

        lines.append(f"CUDA Hardware:        {'Detected' if self.cuda_available else 'Not detected'}")
        if self.cuda_available:
            ver_str = self.cuda_driver_version or "Unknown"
            api_str = str(self.cuda_driver_api_version) if self.cuda_driver_api_version else "Unknown"
            lines.append(f"  Driver Version:     {ver_str} (API: {api_str})")
            lines.append(f"  CUDA 12.4 Support:  {'Compatible' if self.cuda_supported else 'INCOMPATIBLE'}")
            if not self.cuda_supported and self.cuda_incompatibility_reason:
                lines.append(f"  Reason:             {self.cuda_incompatibility_reason}")

        lines.append(f"Vulkan Hardware:      {'Detected' if self.vulkan_available else 'Not detected'}")
        if self.vulkan_available and self.vulkan_device_name:
            lines.append(f"  Device Name:        {self.vulkan_device_name}")

        lines.extend([
            "--------------------------------------------------",
            f"RECOMMENDED BACKEND:  {self.recommended_backend.upper()}",
            f"Target Runtime Build: {PINNED_LLAMA_BUILD}",
            f"Details:              {self.details}",
            "==================================================",
        ])
        return "\n".join(lines)


def _parse_driver_version(ver_str: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse a driver version string into a (major, minor) tuple."""
    if not ver_str or not isinstance(ver_str, str):
        return None
    try:
        major, *rest = ver_str.strip().split(".")
        return int(major), int(rest[0]) if rest else 0
    except (ValueError, TypeError):
        return None


def _probe_nvidia_smi() -> Optional[Tuple[str, int, str]]:
    """Query nvidia-smi for primary GPU name, total VRAM (MB), and driver version."""
    nvsmi: Optional[str] = None
    if sys.platform == "win32":
        # Check standard Windows installation directories first to avoid CWD binary hijacking
        for default_path in (
            Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "nvidia-smi.exe",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
        ):
            if default_path.is_file():
                nvsmi = str(default_path)
                break

    if not nvsmi:
        nvsmi = shutil.which("nvidia-smi")

    if not nvsmi:
        return None

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        res = subprocess.run(
            [nvsmi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.0,
            creationflags=creationflags,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return None

        # Parse output; pick the GPU with the highest VRAM if multiple exist
        best_gpu: Optional[Tuple[str, int, str]] = None
        max_vram = -1
        for line in res.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                name = parts[0]
                try:
                    vram = int(float(parts[1]))
                except ValueError:
                    vram = 0
                driver = parts[2]
                if vram > max_vram:
                    max_vram = vram
                    best_gpu = (name, vram, driver)

        return best_gpu
    except Exception as exc:
        logger.debug("nvidia-smi probe failed: %s", exc)
        return None


def _probe_nvcuda_ctypes() -> Optional[int]:
    """Query nvcuda.dll for driver API version via cuDriverGetVersion."""
    if sys.platform != "win32":
        return None

    import ctypes

    try:
        cuda_path = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "nvcuda.dll"
        if not cuda_path.is_file():
            return None

        nvcuda = ctypes.windll.LoadLibrary(str(cuda_path))
        if not hasattr(nvcuda, "cuInit") or not hasattr(nvcuda, "cuDriverGetVersion"):
            return None

        ret = nvcuda.cuInit(0)
        if ret != 0:  # CUDA_SUCCESS is 0
            return None

        ver = ctypes.c_int(0)
        if nvcuda.cuDriverGetVersion(ctypes.byref(ver)) == 0:
            return ver.value
    except Exception as exc:
        logger.debug("nvcuda ctypes probe failed: %s", exc)
    return None


def _probe_wsl() -> bool:
    """Detect if running under Linux WSL (Windows Subsystem for Linux)."""
    if sys.platform == "win32":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        content = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
        if "microsoft" in content or "wsl" in content:
            return True
    except (OSError, UnicodeDecodeError):
        pass
    try:
        return Path("/dev/dxg").exists() or Path("/usr/lib/wsl/lib").is_dir()
    except OSError:
        return False


def _probe_vulkan_ctypes() -> Tuple[bool, Optional[str]]:
    """Probe Vulkan 1.2+ physical devices via pure ctypes."""
    import ctypes

    try:
        vk = None
        if sys.platform == "win32":
            vk_path = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "vulkan-1.dll"
            if not vk_path.is_file():
                return False, None
            vk = ctypes.CDLL(str(vk_path))
        else:
            candidates = ["libvulkan.so.1", "libvulkan.so"]
            if _probe_wsl():
                candidates.append("/usr/lib/wsl/lib/libvulkan.so.1")

            for cand in candidates:
                try:
                    vk = ctypes.CDLL(cand)
                    if vk:
                        break
                except Exception:
                    continue

        if not vk:
            return False, None

        class VkInstanceCreateInfo(ctypes.Structure):
            _fields_ = [
                ("sType", ctypes.c_int),
                ("pNext", ctypes.c_void_p),
                ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.c_void_p),
                ("enabledLayerCount", ctypes.c_uint32),
                ("ppEnabledLayerNames", ctypes.c_void_p),
                ("enabledExtensionCount", ctypes.c_uint32),
                ("ppEnabledExtensionNames", ctypes.c_void_p),
            ]

        # Set argument types for 64-bit safety
        vk.vkCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        vk.vkEnumeratePhysicalDevices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        vk.vkGetPhysicalDeviceProperties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        vk.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        info = VkInstanceCreateInfo(sType=1)
        instance = ctypes.c_void_p()
        if vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance)) != 0 or not instance.value:
            return False, None

        try:
            count = ctypes.c_uint32(0)
            vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
            if count.value == 0:
                return False, None

            devices = (ctypes.c_void_p * count.value)()
            vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices)

            # Prioritize discrete GPU (deviceType == 2) over integrated GPU (deviceType == 1).
            # VkPhysicalDeviceProperties in C is ~824+ bytes due to VkPhysicalDeviceLimits.
            # Using a 2048-byte buffer avoids buffer overrun while cleanly reading deviceType
            # at offset 16 (uint32) and deviceName at offset 20 (char[256]).
            best_device_name: Optional[str] = None

            for dev in devices:
                props_buf = ctypes.create_string_buffer(2048)
                vk.vkGetPhysicalDeviceProperties(dev, props_buf)
                dev_type = int.from_bytes(props_buf.raw[16:20], "little")
                dev_name = props_buf.raw[20:276].split(b"\x00")[0].decode("utf-8", "replace").strip()
                if dev_type in (0, 4):  # Skip OTHER and CPU / Lavapipe / llvmpipe rasterizers
                    continue
                if dev_type == 2:  # VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
                    best_device_name = dev_name
                    break
                if not best_device_name:
                    best_device_name = dev_name

            if not best_device_name:
                return False, None
            return True, best_device_name
        finally:
            vk.vkDestroyInstance(instance, None)

    except Exception as exc:
        logger.debug("Vulkan ctypes probe failed: %s", exc)
        return False, None


def _probe_cpu_info() -> str:
    """Retrieve processor name and architecture."""
    proc = platform.processor() or platform.machine()
    return proc.strip() or "x86_64"


_SYSFS_DRM_PATH: Path = Path("/sys/class/drm")


def _probe_linux_drm_sysfs(sysfs_dir: Optional[Path] = None) -> Optional[Tuple[str, int]]:
    """Inspect Linux DRM sysfs interface (/sys/class/drm) for installed GPUs.

    Matches PCI vendor IDs to identify discrete GPUs over integrated GPUs:
    - 0x10de: NVIDIA (discrete)
    - 0x1002: AMD (discrete)
    - 0x8086: Intel (integrated)
    - 0x1414: Microsoft WSL (integrated)

    Returns:
        (name, vram_mb) of the highest priority GPU, or None.
    """
    drm_path = sysfs_dir if sysfs_dir is not None else _SYSFS_DRM_PATH
    if not drm_path.is_dir():
        return None

    vendor_table = {
        "0x10de": ("NVIDIA GPU", True),
        "0x1002": ("AMD GPU", True),
        "0x8086": ("Intel Graphics", False),
        "0x1414": ("Microsoft WSL GPU", False),
    }

    gpus = []
    try:
        for card_path in drm_path.glob("card[0-9]*"):
            vendor_path = card_path / "device" / "vendor"
            if not vendor_path.is_file():
                continue
            try:
                raw_vendor = vendor_path.read_text(encoding="utf-8").strip().lower()
            except OSError:
                continue

            matched = vendor_table.get(raw_vendor)
            if not matched:
                continue

            name, is_discrete = matched
            vram_mb = 0
            vram_path = card_path / "device" / "mem_info_vram_total"
            if vram_path.is_file():
                try:
                    vram_bytes = int(vram_path.read_text(encoding="utf-8").strip())
                    vram_mb = vram_bytes // (1024 * 1024)
                except (ValueError, OSError):
                    pass

            gpus.append((name, vram_mb, is_discrete))
    except Exception as exc:
        logger.debug("Linux DRM sysfs probe failed: %s", exc)
        return None

    if not gpus:
        return None

    # Discrete GPUs take precedence over integrated GPUs, then highest VRAM
    gpus.sort(key=lambda x: (1 if x[2] else 0, x[1]), reverse=True)
    best = gpus[0]
    return best[0], best[1]



def detect_hardware() -> HardwareProfile:
    """Inspect system hardware and determine the optimal local runtime recommendation.

    Strict Evaluation Flow:
    1. Check NVIDIA GPU presence via nvidia-smi (or nvcuda.dll fallback).
    2. If present, validate driver version against minimum requirement for CUDA 12.4:
       - Windows display driver >= 550.54
       - CUDA driver API version >= 12040
       If driver is too old, CUDA is marked incompatible and evaluation falls through immediately.
    3. Check Vulkan capability via vulkan-1.dll physical device enumeration.
    4. Default to CPU AVX2 if GPU acceleration is unavailable or incompatible.

    Returns:
        HardwareProfile: Immutable hardware snapshot and recommendation.
    """
    cpu_name = _probe_cpu_info()

    gpu_name: Optional[str] = None
    vram_mb: Optional[int] = None
    cuda_driver_version: Optional[str] = None
    cuda_driver_api_version: Optional[int] = None
    cuda_available = False
    cuda_supported = False
    cuda_incompatibility_reason: Optional[str] = None

    smi_res = _probe_nvidia_smi()
    if smi_res is not None:
        gpu_name, vram_mb, cuda_driver_version = smi_res
        cuda_available = True
    elif sys.platform != "win32":
        drm_res = _probe_linux_drm_sysfs()
        if drm_res is not None:
            gpu_name, vram_mb = drm_res

    # Check CUDA driver API version via ctypes
    api_ver = _probe_nvcuda_ctypes()
    if api_ver is not None:
        cuda_driver_api_version = api_ver
        cuda_available = True

    # Validate Driver Version Compatibility if CUDA hardware was detected
    if cuda_available:
        if sys.platform != "win32":
            cuda_supported = False
            cuda_incompatibility_reason = "Managed CUDA runtime is not supported on Linux; using Vulkan or CPU"
        else:
            parsed_driver = _parse_driver_version(cuda_driver_version) if cuda_driver_version else None
            driver_incompatible = False
            reason_parts = []

            if parsed_driver is not None and parsed_driver < MIN_CUDA_DRIVER_VERSION:
                driver_incompatible = True
                min_str = f"{MIN_CUDA_DRIVER_VERSION[0]}.{MIN_CUDA_DRIVER_VERSION[1]}"
                reason_parts.append(
                    f"Installed NVIDIA display driver {cuda_driver_version} does not meet CUDA 12.4 requirement (>= {min_str})"
                )

            if cuda_driver_api_version is not None and cuda_driver_api_version < MIN_CUDA_DRIVER_API_VERSION:
                driver_incompatible = True
                reason_parts.append(
                    f"Driver API version {cuda_driver_api_version} is below CUDA 12.4 requirement (>= {MIN_CUDA_DRIVER_API_VERSION})"
                )

            if parsed_driver is None and cuda_driver_api_version is None:
                driver_incompatible = True
                reason_parts.append(
                    "NVIDIA driver version could not be determined or verified for CUDA 12.4 requirement"
                )

            if driver_incompatible:
                cuda_supported = False
                cuda_incompatibility_reason = "; ".join(reason_parts)
                logger.warning("CUDA hardware detected but driver is incompatible: %s", cuda_incompatibility_reason)
            else:
                cuda_supported = True

    vulkan_available, vulkan_device_name = _probe_vulkan_ctypes()

    if sys.platform != "win32":
        # On Linux, AksaraSight does not bundle or recommend CUDA binaries;
        # route to Vulkan if capable hardware exists, otherwise CPU fallback.
        if vulkan_available:
            rec_backend = "vulkan"
            gpu_name = gpu_name or vulkan_device_name
            if cuda_available or (gpu_name and "nvidia" in gpu_name.lower()):
                details = (
                    f"NVIDIA GPU detected on Linux. Using Vulkan acceleration on '{vulkan_device_name or gpu_name}'."
                )
            else:
                details = f"Vulkan-capable device '{vulkan_device_name or 'GPU'}' detected for hardware acceleration."
        else:
            rec_backend = "cpu"
            if cuda_available or (gpu_name and "nvidia" in gpu_name.lower()):
                details = "NVIDIA GPU detected on Linux but Vulkan is unavailable. Falling back to CPU inference."
            else:
                details = "No hardware acceleration (Vulkan) detected. Falling back to CPU inference."
    else:
        # Windows evaluation flow (CUDA -> Vulkan -> CPU)
        if cuda_available and cuda_supported:
            rec_backend = "cuda"
            vram_info = f" with {vram_mb} MB VRAM" if vram_mb else ""
            details = (
                f"NVIDIA GPU '{gpu_name or 'NVIDIA Device'}'{vram_info} supports CUDA 12.4 acceleration "
                f"(driver: {cuda_driver_version or 'detected'})."
            )
        elif vulkan_available:
            rec_backend = "vulkan"
            if cuda_available and not cuda_supported:
                details = (
                    f"NVIDIA GPU detected but driver is incompatible ({cuda_incompatibility_reason}). "
                    f"Falling back to Vulkan acceleration on '{vulkan_device_name or 'Vulkan Device'}'."
                )
            else:
                gpu_name = gpu_name or vulkan_device_name
                details = f"Vulkan-capable device '{vulkan_device_name or 'GPU'}' detected for hardware acceleration."
        else:
            rec_backend = "cpu"
            if cuda_available and not cuda_supported:
                details = (
                    f"NVIDIA GPU detected but driver is incompatible ({cuda_incompatibility_reason}) "
                    "and Vulkan is unavailable. Falling back to CPU inference."
                )
            else:
                details = "No hardware acceleration (CUDA/Vulkan) detected. Falling back to CPU inference."

    return HardwareProfile(
        gpu_name=gpu_name,
        vram_mb=vram_mb,
        cuda_available=cuda_available,
        cuda_driver_version=cuda_driver_version,
        cuda_driver_api_version=cuda_driver_api_version,
        cuda_supported=cuda_supported,
        cuda_incompatibility_reason=cuda_incompatibility_reason,
        vulkan_available=vulkan_available,
        vulkan_device_name=vulkan_device_name,
        cpu_name=cpu_name,
        recommended_backend=rec_backend,
        details=details,
    )


_CACHED_HARDWARE_PROFILE: Optional[HardwareProfile] = None
_PREWARM_LOCK = threading.Lock()
_PREWARM_THREAD: Optional[threading.Thread] = None


def start_hardware_prewarm() -> None:
    """Pre-warm hardware detection in a background daemon thread if not already cached.

    Ensures subsequent blocking or non-blocking queries return quickly without
    delaying application startup or UI initialization.
    """
    global _PREWARM_THREAD
    if _CACHED_HARDWARE_PROFILE is not None:
        return
    if _PREWARM_THREAD is not None and _PREWARM_THREAD.is_alive():
        return
    if not _PREWARM_LOCK.acquire(blocking=False):
        return
    try:
        if _CACHED_HARDWARE_PROFILE is not None:
            return
        if _PREWARM_THREAD is not None and _PREWARM_THREAD.is_alive():
            return
        t = threading.Thread(
            target=get_cached_hardware_profile,
            kwargs={"blocking": True},
            name="HardwarePrewarmWorker",
            daemon=True,
        )
        _PREWARM_THREAD = t
        t.start()
    finally:
        _PREWARM_LOCK.release()


def get_cached_hardware_profile(
    force_refresh: bool = False,
    blocking: bool = True,
) -> Optional[HardwareProfile]:
    """Retrieve cached HardwareProfile snapshot, computing once and caching in-process.

    Avoids repeated subprocess queries (nvidia-smi) and ctypes device enumerations
    across multiple property accesses in server supervision and UI rendering.

    Args:
        force_refresh: If True, bypasses cache and forces fresh hardware detection.
        blocking: If False, returns None immediately if the cache is empty without
            invoking blocking subprocess queries under state locks.

    Returns:
        HardwareProfile: Cached or newly evaluated system hardware snapshot,
        or None if non-blocking and cache is empty.
    """
    global _CACHED_HARDWARE_PROFILE
    if force_refresh:
        if not blocking:
            return None
        with _PREWARM_LOCK:
            _CACHED_HARDWARE_PROFILE = detect_hardware()
    elif _CACHED_HARDWARE_PROFILE is None:
        if not blocking:
            start_hardware_prewarm()
            return None
        with _PREWARM_LOCK:
            if _CACHED_HARDWARE_PROFILE is None:
                _CACHED_HARDWARE_PROFILE = detect_hardware()
    return _CACHED_HARDWARE_PROFILE


def clear_hardware_cache() -> None:
    """Reset the cached HardwareProfile snapshot (primarily for testing)."""
    global _CACHED_HARDWARE_PROFILE, _PREWARM_THREAD
    with _PREWARM_LOCK:
        _CACHED_HARDWARE_PROFILE = None
        _PREWARM_THREAD = None


def probe_nvml_vram(device_index: Optional[int] = None) -> Dict[str, Any]:
    """Query in-process NVIDIA Management Library (NVML) for real-time VRAM telemetry.

    Searches standard Windows and Linux NVML paths, initializes the library,
    queries device memory and telemetry, and guarantees proper lifecycle cleanup.

    Args:
        device_index: Optional target GPU device index. If None, auto-selects
            the device with the highest total VRAM.

    Returns:
        Dict adhering to hardware VRAM schema with keys: available, device_name,
        device_index, device_count, total_mb, used_mb, free_mb, usage_percent, error.
    """
    import ctypes

    nvml = None
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "nvml.dll",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvml.dll",
        ]
        for cand in candidates:
            if cand.is_file():
                try:
                    nvml = ctypes.CDLL(str(cand))
                    break
                except Exception:
                    continue
    else:
        candidates = [
            "libnvidia-ml.so.1",
            "/usr/lib/wsl/lib/libnvidia-ml.so.1",
        ]
        for cand in candidates:
            try:
                nvml = ctypes.CDLL(str(cand))
                if nvml:
                    break
            except Exception:
                continue

    if not nvml:
        return {
            "available": False,
            "device_name": None,
            "device_index": None,
            "device_count": None,
            "total_mb": None,
            "used_mb": None,
            "free_mb": None,
            "usage_percent": None,
            "error": "NVML library (nvml.dll / libnvidia-ml.so.1) not found",
        }

    init_fn = getattr(nvml, "nvmlInit_v2", getattr(nvml, "nvmlInit", None))
    if not init_fn:
        return {
            "available": False,
            "device_name": None,
            "device_index": None,
            "device_count": None,
            "total_mb": None,
            "used_mb": None,
            "free_mb": None,
            "usage_percent": None,
            "error": "NVML symbol nvmlInit_v2 not found",
        }

    init_ret = init_fn()
    if init_ret != 0:
        return {
            "available": False,
            "device_name": None,
            "device_index": None,
            "device_count": None,
            "total_mb": None,
            "used_mb": None,
            "free_mb": None,
            "usage_percent": None,
            "error": f"nvmlInit_v2 failed with error code {init_ret}",
        }

    class _c_nvmlMemory_t(ctypes.Structure):
        _fields_ = [
            ("total", ctypes.c_ulonglong),
            ("free", ctypes.c_ulonglong),
            ("used", ctypes.c_ulonglong),
        ]

    try:
        get_count_fn = getattr(nvml, "nvmlDeviceGetCount_v2", getattr(nvml, "nvmlDeviceGetCount", None))
        get_handle_fn = getattr(nvml, "nvmlDeviceGetHandleByIndex_v2", getattr(nvml, "nvmlDeviceGetHandleByIndex", None))
        get_name_fn = getattr(nvml, "nvmlDeviceGetName", None)
        get_mem_fn = getattr(nvml, "nvmlDeviceGetMemoryInfo", None)

        if not get_count_fn or not get_handle_fn or not get_mem_fn:
            return {
                "available": False,
                "device_name": None,
                "device_index": None,
                "device_count": None,
                "total_mb": None,
                "used_mb": None,
                "free_mb": None,
                "usage_percent": None,
                "error": "Required NVML symbols not found",
            }

        count = ctypes.c_uint(0)
        ret = get_count_fn(ctypes.byref(count))
        if ret != 0 or count.value == 0:
            return {
                "available": False,
                "device_name": None,
                "device_index": None,
                "device_count": count.value,
                "total_mb": None,
                "used_mb": None,
                "free_mb": None,
                "usage_percent": None,
                "error": "No NVIDIA devices found or query failed",
            }

        device_count = count.value

        if device_index is not None:
            if device_index < 0 or device_index >= device_count:
                return {
                    "available": False,
                    "device_name": None,
                    "device_index": device_index,
                    "device_count": device_count,
                    "total_mb": None,
                    "used_mb": None,
                    "free_mb": None,
                    "usage_percent": None,
                    "error": f"Device index {device_index} out of range (device_count={device_count})",
                }

        best_index: Optional[int] = None
        best_name: str = "NVIDIA GPU"
        best_total = 0
        best_used = 0
        best_free = 0
        found = False

        if device_index is not None:
            indices_to_query = [device_index]
        else:
            indices_to_query = list(range(device_count))

        max_total_bytes = -1

        for idx in indices_to_query:
            dev_handle = ctypes.c_void_p()
            if get_handle_fn(ctypes.c_uint(idx), ctypes.byref(dev_handle)) != 0:
                continue

            mem = _c_nvmlMemory_t()
            if get_mem_fn(dev_handle, ctypes.byref(mem)) != 0:
                continue

            name = f"NVIDIA GPU #{idx}"
            if get_name_fn:
                name_buf = ctypes.create_string_buffer(96)
                if get_name_fn(dev_handle, name_buf, ctypes.c_uint(len(name_buf))) == 0:
                    name = name_buf.value.decode("utf-8", errors="replace").strip() or name

            if mem.total > max_total_bytes:
                max_total_bytes = mem.total
                best_index = idx
                best_name = name
                best_total = mem.total
                best_used = mem.used
                best_free = mem.free
                found = True

        if not found or best_index is None:
            return {
                "available": False,
                "device_name": None,
                "device_index": device_index,
                "device_count": device_count,
                "total_mb": None,
                "used_mb": None,
                "free_mb": None,
                "usage_percent": None,
                "error": "Failed to query VRAM memory info from target device",
            }

        total_mb = int(best_total // (1024 * 1024))
        used_mb = int(best_used // (1024 * 1024))
        free_mb = int(best_free // (1024 * 1024))
        usage_pct = round((best_used / best_total) * 100.0, 1) if best_total > 0 else 0.0

        return {
            "available": True,
            "device_name": best_name,
            "device_index": best_index,
            "device_count": device_count,
            "total_mb": total_mb,
            "used_mb": used_mb,
            "free_mb": free_mb,
            "usage_percent": usage_pct,
            "error": None,
        }
    except Exception as exc:
        logger.debug("NVML query exception: %s", exc)
        return {
            "available": False,
            "device_name": None,
            "device_index": device_index,
            "device_count": None,
            "total_mb": None,
            "used_mb": None,
            "free_mb": None,
            "usage_percent": None,
            "error": f"NVML query exception: {exc}",
        }
    finally:
        shutdown_fn = getattr(nvml, "nvmlShutdown", None)
        if shutdown_fn:
            try:
                shutdown_fn()
            except Exception as exc:
                logger.debug("nvmlShutdown failed: %s", exc)


