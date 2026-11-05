"""Unit and functional tests for hardware capability detection engine."""

import sys
from unittest.mock import MagicMock, patch
from core.hardware import (
    HardwareProfile,
    PINNED_LLAMA_BUILD,
    _parse_driver_version,
    _probe_nvidia_smi,
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
    assert _parse_driver_version(None) is None


def test_detect_hardware_cuda_compatible(monkeypatch) -> None:
    """NVIDIA GPU with modern driver (>= 550.54 / API >= 12040) recommends CUDA."""
    monkeypatch.setattr("sys.platform", "win32")
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


def test_detect_hardware_cuda_outdated_driver_falls_through_to_vulkan(monkeypatch) -> None:
    """NVIDIA GPU with driver older than 550.54 falls through immediately to Vulkan."""
    monkeypatch.setattr(sys, "platform", "win32")
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


def test_detect_hardware_nvidia_smi_missing_fallback_to_nvcuda_dll(monkeypatch) -> None:
    """When nvidia-smi is not in PATH, nvcuda.dll ctypes probe satisfies CUDA check."""
    monkeypatch.setattr("sys.platform", "win32")
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


def test_detect_hardware_cuda_unverified_driver_fails_closed(monkeypatch) -> None:
    """When CUDA GPU is detected via nvidia-smi but driver version is unverified, CUDA fails closed."""
    monkeypatch.setattr(sys, "platform", "win32")
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=("NVIDIA GPU", 4096, "")),
        patch("core.hardware._probe_nvcuda_ctypes", return_value=None),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(True, "NVIDIA GPU")),
        patch("core.hardware._probe_cpu_info", return_value="x86_64"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is True
        assert profile.cuda_supported is False
        assert "could not be determined or verified" in (profile.cuda_incompatibility_reason or "")
        assert profile.recommended_backend == "vulkan"


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
    """Verify detect_hardware() executes cleanly on real host environment without raising.

    CAVEAT / AUDIT NOTE:
    This smoke test runs against whatever physical or virtual hardware is present
    on the host machine (invoking real nvidia-smi, nvcuda.dll, or vulkan-1.dll).
    It is an environment diagnostic probe, NOT a deterministic hardware-independent
    contract test. Deterministic behavior across CUDA/Vulkan/CPU fallback paths is
    verified independently via mocked unit tests above.
    """
    profile = detect_hardware()
    assert isinstance(profile, HardwareProfile)
    assert profile.recommended_backend in {"cuda", "vulkan", "cpu"}
    assert len(profile.cpu_name) > 0
    assert len(profile.details) > 0
    summary = profile.format_summary()
    assert "SYSTEM HARDWARE DETECTION REPORT" in summary



def test_probe_nvidia_smi_prioritizes_system_paths_over_shutil_which() -> None:
    """Verify _probe_nvidia_smi checks known System32/Program Files paths before shutil.which."""
    from pathlib import Path

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "NVIDIA GeForce RTX 4090, 24576, 555.85\n"

    # Case 1: System32 path exists on Windows -> shutil.which MUST NOT be called
    def fake_is_file(self: Path) -> bool:
        return "System32" in str(self) and "nvidia-smi.exe" in str(self)

    with (
        patch("sys.platform", "win32"),
        patch.object(Path, "is_file", fake_is_file),
        patch("shutil.which") as mock_which,
        patch("subprocess.run", return_value=mock_res) as mock_run,
    ):
        result = _probe_nvidia_smi()
        assert result == ("NVIDIA GeForce RTX 4090", 24576, "555.85")
        mock_which.assert_not_called()
        # Verify run was called with the absolute System32 path
        called_binary = mock_run.call_args[0][0][0]
        assert called_binary.endswith("System32\\nvidia-smi.exe") or called_binary.endswith("System32/nvidia-smi.exe")

    # Case 2: Neither system path exists -> falls back to shutil.which
    with (
        patch("sys.platform", "win32"),
        patch.object(Path, "is_file", return_value=False),
        patch("shutil.which", return_value="C:\\custom\\nvidia-smi.exe") as mock_which,
        patch("subprocess.run", return_value=mock_res) as mock_run,
    ):
        result = _probe_nvidia_smi()
        assert result == ("NVIDIA GeForce RTX 4090", 24576, "555.85")
        mock_which.assert_called_once_with("nvidia-smi")
        called_binary = mock_run.call_args[0][0][0]
        assert called_binary == "C:\\custom\\nvidia-smi.exe"


def test_start_hardware_prewarm() -> None:
    """Verify start_hardware_prewarm launches worker thread and populates cache."""
    from core.hardware import (
        clear_hardware_cache,
        get_cached_hardware_profile,
        start_hardware_prewarm,
    )

    clear_hardware_cache()
    try:
        dummy_profile = HardwareProfile(
            gpu_name="Test GPU",
            vram_mb=4096,
            cuda_available=True,
            cpu_name="Test CPU",
            recommended_backend="cuda",
        )
        with patch("core.hardware.detect_hardware", return_value=dummy_profile) as mock_detect:
            # Cold-start non-blocking query should return None and trigger prewarm
            res = get_cached_hardware_profile(blocking=False)
            assert res is None

            # Calling prewarm again when worker is running is a safe no-op
            start_hardware_prewarm()

            # Wait for cached profile to be populated
            profile = get_cached_hardware_profile(blocking=True)
            assert profile == dummy_profile
            mock_detect.assert_called_once()

            # Subsequent start_hardware_prewarm when cache is full is a no-op
            start_hardware_prewarm()
            mock_detect.assert_called_once()
    finally:
        clear_hardware_cache()


def test_start_hardware_prewarm_non_blocking_when_lock_held() -> None:
    """Verify start_hardware_prewarm and get_cached_hardware_profile(blocking=False) do not block when lock is held."""
    import time
    from core.hardware import (
        _PREWARM_LOCK,
        clear_hardware_cache,
        get_cached_hardware_profile,
        start_hardware_prewarm,
    )

    clear_hardware_cache()
    try:
        acquired = _PREWARM_LOCK.acquire(blocking=False)
        assert acquired, "Failed to acquire _PREWARM_LOCK for test setup"
        try:
            start_t = time.perf_counter()
            start_hardware_prewarm()
            elapsed_prewarm = time.perf_counter() - start_t
            assert elapsed_prewarm < 0.05, f"start_hardware_prewarm took too long: {elapsed_prewarm}s"

            start_t = time.perf_counter()
            res = get_cached_hardware_profile(blocking=False)
            elapsed_query = time.perf_counter() - start_t
            assert res is None
            assert elapsed_query < 0.05, f"get_cached_hardware_profile(blocking=False) took too long: {elapsed_query}s"
        finally:
            _PREWARM_LOCK.release()
    finally:
        clear_hardware_cache()


def test_hardware_detection_single_flight_under_concurrent_queries() -> None:
    """Verify concurrent prewarm and blocking queries result in a single hardware detection flight."""
    import threading
    import time
    import core.hardware
    from core.hardware import (
        clear_hardware_cache,
        get_cached_hardware_profile,
        start_hardware_prewarm,
    )

    clear_hardware_cache()
    try:
        dummy_profile = HardwareProfile(
            gpu_name="Test GPU",
            vram_mb=4096,
            cuda_available=True,
            cpu_name="Test CPU",
            recommended_backend="cuda",
        )

        def slow_detect() -> HardwareProfile:
            time.sleep(0.05)
            return dummy_profile

        with patch("core.hardware.detect_hardware", side_effect=slow_detect) as mock_detect:
            results: list = [None, None]

            def run_prewarm() -> None:
                start_hardware_prewarm()

            def run_get_profile(idx: int) -> None:
                results[idx] = get_cached_hardware_profile(blocking=True)

            threads = [
                threading.Thread(target=run_prewarm),
                threading.Thread(target=run_get_profile, args=(0,)),
                threading.Thread(target=run_get_profile, args=(1,)),
            ]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if core.hardware._PREWARM_THREAD is not None:
                core.hardware._PREWARM_THREAD.join(timeout=2.0)

            assert mock_detect.call_count == 1
            assert results[0] == dummy_profile
            assert results[1] == dummy_profile
    finally:
        clear_hardware_cache()


def test_probe_vulkan_ctypes_anchored_to_system32(monkeypatch) -> None:
    """Verify _probe_vulkan_ctypes never falls back to relative vulkan-1.dll when missing from System32."""
    import sys
    from core.hardware import _probe_vulkan_ctypes

    monkeypatch.setattr(sys, "platform", "win32")
    with patch("pathlib.Path.is_file", return_value=False):
        with patch("ctypes.CDLL") as mock_cdll:
            available, name = _probe_vulkan_ctypes()
            assert available is False
            assert name is None
            mock_cdll.assert_not_called()


def test_detect_hardware_linux_nvidia_routes_to_vulkan_when_available(monkeypatch) -> None:
    """Linux system with NVIDIA GPU and Vulkan support routes to Vulkan (never CUDA)."""
    monkeypatch.setattr("sys.platform", "linux")
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=("NVIDIA GeForce RTX 3060", 12288, "550.54")),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(True, "NVIDIA GeForce RTX 3060")),
        patch("core.hardware._probe_cpu_info", return_value="x86_64"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is True
        assert profile.cuda_supported is False
        assert "Managed CUDA runtime is not supported on Linux" in (profile.cuda_incompatibility_reason or "")
        assert profile.recommended_backend == "vulkan"
        assert profile.recommended_backend != "cuda"
        assert "Vulkan" in profile.details


def test_detect_hardware_linux_nvidia_routes_to_cpu_when_vulkan_unavailable(monkeypatch) -> None:
    """Linux system with NVIDIA GPU but no Vulkan routes to CPU (never CUDA)."""
    monkeypatch.setattr("sys.platform", "linux")
    with (
        patch("core.hardware._probe_nvidia_smi", return_value=("NVIDIA GeForce RTX 3060", 12288, "550.54")),
        patch("core.hardware._probe_vulkan_ctypes", return_value=(False, None)),
        patch("core.hardware._probe_cpu_info", return_value="x86_64"),
    ):
        profile = detect_hardware()
        assert profile.cuda_available is True
        assert profile.cuda_supported is False
        assert "Managed CUDA runtime is not supported on Linux" in (profile.cuda_incompatibility_reason or "")
        assert profile.recommended_backend == "cpu"
        assert profile.recommended_backend != "cuda"


def test_probe_vulkan_linux_libvulkan_so(monkeypatch) -> None:
    """Linux ctypes probe loads libvulkan.so.1 / libvulkan.so and enumerates physical devices."""
    import ctypes
    from core.hardware import _probe_vulkan_ctypes

    monkeypatch.setattr("sys.platform", "linux")

    mock_vk = MagicMock()

    def fake_create_instance(info, alloc, p_inst):
        ctypes.cast(p_inst, ctypes.POINTER(ctypes.c_void_p)).contents.value = 0x12345678
        return 0

    def fake_enumerate(inst, p_count, p_devs):
        if p_devs is None:
            ctypes.cast(p_count, ctypes.POINTER(ctypes.c_uint32)).contents.value = 1
        else:
            p_devs[0] = 0xDEADBEEF
        return 0

    def fake_get_props(dev, buf):
        # deviceType == 2 is VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
        buf[16:20] = (2).to_bytes(4, "little")
        name_bytes = b"Vulkan API Discrete GPU\x00"
        buf[20 : 20 + len(name_bytes)] = name_bytes

    mock_vk.vkCreateInstance.side_effect = fake_create_instance
    mock_vk.vkEnumeratePhysicalDevices.side_effect = fake_enumerate
    mock_vk.vkGetPhysicalDeviceProperties.side_effect = fake_get_props
    mock_vk.vkDestroyInstance.return_value = 0

    with patch("ctypes.CDLL", return_value=mock_vk) as mock_cdll:
        available, dev_name = _probe_vulkan_ctypes()
        assert mock_cdll.called, "Vulkan library must be loaded via ctypes.CDLL on Linux"
        assert available is True
        assert dev_name == "Vulkan API Discrete GPU"


def test_probe_vulkan_linux_lavapipe_rejected(monkeypatch) -> None:
    """Vulkan physical device with deviceType == 4 (CPU / Lavapipe rasterizer) is rejected."""
    import ctypes
    from core.hardware import _probe_vulkan_ctypes

    monkeypatch.setattr("sys.platform", "linux")

    mock_vk = MagicMock()

    def fake_create_instance(info, alloc, p_inst):
        ctypes.cast(p_inst, ctypes.POINTER(ctypes.c_void_p)).contents.value = 0x12345678
        return 0

    def fake_enumerate(inst, p_count, p_devs):
        if p_devs is None:
            ctypes.cast(p_count, ctypes.POINTER(ctypes.c_uint32)).contents.value = 1
        else:
            p_devs[0] = 0xDEADBEEF
        return 0

    def fake_get_props(dev, buf):
        # deviceType == 4 is VK_PHYSICAL_DEVICE_TYPE_CPU (Lavapipe/llvmpipe)
        buf[16:20] = (4).to_bytes(4, "little")
        name_bytes = b"llvmpipe (LLVM 15.0.7, 256 bits)\x00"
        buf[20 : 20 + len(name_bytes)] = name_bytes

    mock_vk.vkCreateInstance.side_effect = fake_create_instance
    mock_vk.vkEnumeratePhysicalDevices.side_effect = fake_enumerate
    mock_vk.vkGetPhysicalDeviceProperties.side_effect = fake_get_props
    mock_vk.vkDestroyInstance.return_value = 0

    with patch("ctypes.CDLL", return_value=mock_vk) as mock_cdll:
        available, dev_name = _probe_vulkan_ctypes()
        assert mock_cdll.called, "Vulkan library must be loaded via ctypes.CDLL on Linux"
        assert available is False
        assert dev_name is None


def test_probe_linux_drm_sysfs_discrete_over_integrated(monkeypatch, tmp_path) -> None:
    """DRM sysfs probe prioritizes discrete GPU (NVIDIA 0x10de) over integrated GPU (Intel 0x8086)."""
    import core.hardware

    monkeypatch.setattr("sys.platform", "linux")
    drm_dir = tmp_path / "sys" / "class" / "drm"
    card0 = drm_dir / "card0" / "device"
    card0.mkdir(parents=True)
    (card0 / "vendor").write_text("0x8086\n", encoding="utf-8")

    card1 = drm_dir / "card1" / "device"
    card1.mkdir(parents=True)
    (card1 / "vendor").write_text("0x10de\n", encoding="utf-8")
    (card1 / "mem_info_vram_total").write_text("8589934592\n", encoding="utf-8")

    probe_fn = getattr(core.hardware, "_probe_linux_drm_sysfs", None)
    assert callable(probe_fn), "_probe_linux_drm_sysfs must be implemented in core.hardware"

    if hasattr(core.hardware, "_SYSFS_DRM_PATH"):
        monkeypatch.setattr(core.hardware, "_SYSFS_DRM_PATH", drm_dir)
    try:
        res = probe_fn(sysfs_dir=drm_dir)
    except TypeError:
        res = probe_fn()

    assert res is not None
    res_str = str(res).lower()
    assert "10de" in res_str or "nvidia" in res_str


def test_probe_linux_wsl_detection(monkeypatch) -> None:
    """Linux environment with /dev/dxg or /usr/lib/wsl/lib is identified as WSL."""
    import core.hardware
    from pathlib import Path

    monkeypatch.setattr(sys, "platform", "linux")
    probe_fn = core.hardware._probe_wsl
    assert callable(probe_fn), "_probe_wsl must be implemented in core.hardware"

    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)

    real_read_text = Path.read_text
    def fake_read_text(self: Path, *args, **kwargs) -> str:
        if self.as_posix() == "/proc/version":
            return "Linux version 6.5.0-generic (buildd@canonical)"
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    real_is_file = Path.is_file
    def fake_is_file(self: Path, *args, **kwargs) -> bool:
        if self.as_posix() == "/proc/version":
            return True
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    def fake_exists_dxg(self: Path) -> bool:
        return self.as_posix() == "/dev/dxg"

    def fake_is_dir_wsl_lib(self: Path) -> bool:
        return self.as_posix() == "/usr/lib/wsl/lib"

    with patch.object(Path, "exists", fake_exists_dxg), patch.object(Path, "is_dir", return_value=False):
        assert probe_fn() is True

    with patch.object(Path, "exists", return_value=False), patch.object(Path, "is_dir", fake_is_dir_wsl_lib):
        assert probe_fn() is True

    with patch.object(Path, "exists", return_value=False), patch.object(Path, "is_dir", return_value=False):
        assert probe_fn() is False

