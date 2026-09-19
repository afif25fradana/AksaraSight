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
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Pinned build tag validated in Phase 4 against GLM-OCR-GGUF
PINNED_LLAMA_BUILD = "b10930"

# CUDA 12.4 driver thresholds on Windows:
# - Minimum display driver version: 550.54
# - Minimum CUDA driver API version: 12040 (cuDriverGetVersion)
MIN_CUDA_DRIVER_VERSION: Tuple[int, int] = (550, 54)
MIN_CUDA_DRIVER_API_VERSION: int = 12040

# Minimum recommended VRAM for GLM-OCR (requires ~2.18 GB under -c 8192 --parallel 1)
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

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
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
        nvcuda = ctypes.windll.LoadLibrary("nvcuda.dll")
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


def _probe_vulkan_ctypes() -> Tuple[bool, Optional[str]]:
    """Probe Vulkan 1.2+ physical devices via vulkan-1.dll using pure ctypes."""
    if sys.platform != "win32":
        return False, None

    import ctypes

    try:
        vk_path = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "vulkan-1.dll"
        if not vk_path.is_file():
            # Try dynamic load if not in System32
            vk = ctypes.CDLL("vulkan-1.dll")
        else:
            vk = ctypes.CDLL(str(vk_path))

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
                if dev_type == 2:  # VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
                    best_device_name = dev_name
                    break
                if not best_device_name:
                    best_device_name = dev_name

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

    # 1. NVIDIA / CUDA Detection
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

    # Check CUDA driver API version via ctypes
    api_ver = _probe_nvcuda_ctypes()
    if api_ver is not None:
        cuda_driver_api_version = api_ver
        cuda_available = True

    # Validate Driver Version Compatibility if CUDA hardware was detected
    if cuda_available:
        parsed_driver = _parse_driver_version(cuda_driver_version) if cuda_driver_version else None
        driver_too_old = False
        reason_parts = []

        if parsed_driver is not None and parsed_driver < MIN_CUDA_DRIVER_VERSION:
            driver_too_old = True
            min_str = f"{MIN_CUDA_DRIVER_VERSION[0]}.{MIN_CUDA_DRIVER_VERSION[1]}"
            reason_parts.append(
                f"Installed NVIDIA display driver {cuda_driver_version} does not meet CUDA 12.4 requirement (>= {min_str})"
            )

        if cuda_driver_api_version is not None and cuda_driver_api_version < MIN_CUDA_DRIVER_API_VERSION:
            driver_too_old = True
            reason_parts.append(
                f"Driver API version {cuda_driver_api_version} is below CUDA 12.4 requirement (>= {MIN_CUDA_DRIVER_API_VERSION})"
            )

        if driver_too_old:
            cuda_supported = False
            cuda_incompatibility_reason = "; ".join(reason_parts)
            logger.warning("CUDA hardware detected but driver is incompatible: %s", cuda_incompatibility_reason)
        else:
            cuda_supported = True

    # 2. Vulkan Detection
    vulkan_available, vulkan_device_name = _probe_vulkan_ctypes()

    # 3. Decision Matrix
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


def get_cached_hardware_profile(force_refresh: bool = False) -> HardwareProfile:
    """Retrieve cached HardwareProfile snapshot, computing once and caching in-process.

    Avoids repeated subprocess queries (nvidia-smi) and ctypes device enumerations
    across multiple property accesses in server supervision and UI rendering.

    Args:
        force_refresh: If True, bypasses cache and forces fresh hardware detection.

    Returns:
        HardwareProfile: Cached or newly evaluated system hardware snapshot.
    """
    global _CACHED_HARDWARE_PROFILE
    if force_refresh or _CACHED_HARDWARE_PROFILE is None:
        _CACHED_HARDWARE_PROFILE = detect_hardware()
    return _CACHED_HARDWARE_PROFILE


def clear_hardware_cache() -> None:
    """Reset the cached HardwareProfile snapshot (primarily for testing)."""
    global _CACHED_HARDWARE_PROFILE
    _CACHED_HARDWARE_PROFILE = None

