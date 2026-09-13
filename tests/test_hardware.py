"""Unit and functional tests for hardware capability detection engine."""

from unittest.mock import MagicMock, patch
import pytest

from core.hardware import (
    HardwareProfile,
    MIN_CUDA_DRIVER_API_VERSION,
    MIN_CUDA_DRIVER_VERSION,
    PINNED_LLAMA_BUILD,
    _parse_driver_version,
    detect_hardware,
)


def test_parse_driver_version() -> None:
    """Verify parsing of display driver strings into major/minor tuples."""
    assert _parse_driver_version("550.54") == (550, 54)
    assert _parse_driver_version("616.56") == (616, 56)
    assert _parse_driver_version("527.41") == (527, 41)
    assert _parse_driver_version("512") == (512, 0)
    assert _parse_driver_version("  551.76  ") == (551, 76)
    assert _parse_driver_version("") is None
    assert _parse_driver_version("invalid") is None
    assert _parse_driver_version(None) is None  # type: ignore[arg-type]


def test_detect_hardware_cuda_compatible() -> None:
    """NVIDIA GPU with modern driver (>= 550.54 / API >= 12040) recommends CUDA."""
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=("NVIDIA GeForce RTX 4090", 24576, "555.85")),
        patch("core.hardware._probe_nvcuda_ctypes", return_value=12040),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(True, "NVIDIA GeForce RTX 4090")),
        patch("core.hardware._probe_cpu_info", return_value="AMD64 Family 25 Model 97 Stepping 2"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is True
        assert profile.cuda_supported is True
        assert profile.cuda_incompatibility_reason is None
        assert profile.recommended_backend == "cuda"
        assert profile.gpu_name == "NVIDIA GeForce RTX 4090"
        assert profile.vram_mb == 24576
        assert "CUDA 12.4 acceleration" in profile.details
        assert "555.85" in profile.details


def test_detect_hardware_cuda_outdated_driver_falls_through_to_vulkan() -> None:
    """NVIDIA GPU with driver older than 550.54 falls through immediately to Vulkan."""
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=("NVIDIA GeForce GTX 1080", 8192, "512.15")),
        patch("core.hardware._probe_nvcuda_ctypes", return_value=11060),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(True, "NVIDIA GeForce GTX 1080")),
        patch("core.hardware._probe_cpu_info", return_value="Intel64 Family 6 Model 154"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is True
        assert profile.cuda_supported is False
        assert profile.cuda_incompatibility_reason is not None
        assert "512.15" in profile.cuda_incompatibility_reason
        assert profile.vulkan_available is True
        # Critical requirement: falls through to Vulkan before any download attempt
        assert profile.recommended_backend == "vulkan"
        assert "Falling back to Vulkan" in profile.details


def test_detect_hardware_cuda_outdated_driver_no_vulkan_falls_through_to_cpu() -> None:
    """NVIDIA GPU with outdated driver and no Vulkan falls through to CPU."""
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=("NVIDIA Quadro P600", 2048, "472.12")),
        patch("core.hardware._probe_nvcuda_ctypes", return_value=11040),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(False, None)),
        patch("core.hardware._probe_cpu_info", return_value="x86_64"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is True
        assert profile.cuda_supported is False
        assert profile.vulkan_available is False
        assert profile.recommended_backend == "cpu"
        assert "Falling back to CPU" in profile.details


def test_detect_hardware_non_nvidia_vulkan_gpu() -> None:
    """System with non-NVIDIA GPU (Intel Iris / AMD) and Vulkan recommends Vulkan."""
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=None),
        patch("core.hardware._probe_nvcuda_ctypes", return_value=None),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(True, "Intel(R) Iris(R) Xe Graphics")),
        patch("core.hardware._probe_cpu_info", return_value="Intel Core i7-12700H"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is False
        assert profile.cuda_supported is False
        assert profile.vulkan_available is True
        assert profile.vulkan_device_name == "Intel(R) Iris(R) Xe Graphics"
        assert profile.recommended_backend == "vulkan"
        assert "Intel(R) Iris(R) Xe Graphics" in profile.details


def test_detect_hardware_cpu_only() -> None:
    """System without CUDA or Vulkan capabilities defaults to CPU inference."""
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=None),
        patch("core.hardware._probe_nvcuda_ctypes", return_value=None),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(False, None)),
        patch("core.hardware._probe_cpu_info", return_value="AMD Ryzen 7 5800X"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is False
        assert profile.vulkan_available is False
        assert profile.recommended_backend == "cpu"
        assert "No hardware acceleration" in profile.details


def test_detect_hardware_nvidia_smi_missing_fallback_to_nvcuda_dll() -> None:
    """When nvidia-smi is not in PATH, nvcuda.dll ctypes probe satisfies CUDA check."""
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=None),
        patch("core.hardware._probe_nvcuda_ctypes", return_value=12040),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(True, "NVIDIA GeForce RTX 3050")),
        patch("core.hardware._probe_cpu_info", return_value="x86_64"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is True
        assert profile.cuda_supported is True
        assert profile.cuda_driver_api_version == 12040
        assert profile.recommended_backend == "cuda"


def test_hardware_profile_format_summary() -> None:
    """Ensure format_summary produces structured, readable output."""
    profile = HardwareProfile(
        gpu_name="NVIDIA GeForce RTX 3050 Laptop GPU",
        vram_mb=6144,
        cuda_available=True,
        cuda_driver_version="551.76",
        cuda_driver_api_version=12040,
        cuda_supported=True,
        vulkan_available=True,
        vulkan_device_name="NVIDIA GeForce RTX 3050 Laptop GPU",
        cpu_name="Intel Core i7-12700H",
        recommended_backend="cuda",
        details="NVIDIA GPU supports CUDA 12.4 acceleration.",
    )
    summary = profile.format_summary()
    assert "SYSTEM HARDWARE DETECTION REPORT" in summary
    assert "NVIDIA GeForce RTX 3050 Laptop GPU" in summary
    assert "6144 MB" in summary
    assert "551.76" in summary
    assert "RECOMMENDED BACKEND:  CUDA" in summary
    assert f"Target Runtime Build: {PINNED_LLAMA_BUILD}" in summary


def test_real_hardware_smoke() -> None:
    """Verify detect_hardware() executes cleanly on real host environment without raising."""
    profile = detect_hardware()
    assert isinstance(profile, HardwareProfile)
    assert profile.recommended_backend in {"cuda", "vulkan", "cpu"}
    assert len(profile.cpu_name) > 0
    assert len(profile.details) > 0
    summary = profile.format_summary()
    assert "SYSTEM HARDWARE DETECTION REPORT" in summary
