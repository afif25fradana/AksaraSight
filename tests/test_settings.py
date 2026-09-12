"""Unit tests for config/settings.py."""

from pathlib import Path
import pytest
from config.settings import Settings, VALID_BACKENDS


def test_default_settings(monkeypatch):
    """Verify default Settings values when no environment variables are present."""
    for var in [
        "OCR_BACKEND", "BACKEND",
        "OCR_ENDPOINT", "LOCAL_ENDPOINT",
        "OCR_TIMEOUT", "TIMEOUT",
        "OCR_MAX_RETRIES", "MAX_RETRIES",
    ]:
        monkeypatch.delenv(var, raising=False)

    s = Settings.from_env()
    assert s.backend == "llama-cpp"
    assert s.local_endpoint == "http://localhost:8080/v1"
    assert s.timeout == 60.0
    assert s.max_retries == 2


def test_settings_ocr_prefixed_env(monkeypatch):
    """Verify loading from OCR_-prefixed environment variables."""
    monkeypatch.setenv("OCR_BACKEND", "ollama")
    monkeypatch.setenv("OCR_ENDPOINT", "http://localhost:11434/v1/")
    monkeypatch.setenv("OCR_TIMEOUT", "120")
    monkeypatch.setenv("OCR_MAX_RETRIES", "5")

    s = Settings.from_env()
    assert s.backend == "ollama"
    assert s.local_endpoint == "http://localhost:11434/v1"  # Trailing slash stripped
    assert s.timeout == 120.0
    assert s.max_retries == 5


def test_settings_bare_env_fallback(monkeypatch):
    """Verify fallback to bare environment variable names from phase-1-core spec."""
    monkeypatch.delenv("OCR_BACKEND", raising=False)
    monkeypatch.delenv("OCR_ENDPOINT", raising=False)
    monkeypatch.delenv("OCR_TIMEOUT", raising=False)
    monkeypatch.delenv("OCR_MAX_RETRIES", raising=False)

    monkeypatch.setenv("BACKEND", "vllm")
    monkeypatch.setenv("LOCAL_ENDPOINT", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("TIMEOUT", "45.5")
    monkeypatch.setenv("MAX_RETRIES", "3")

    s = Settings.from_env()
    assert s.backend == "vllm"
    assert s.local_endpoint == "http://127.0.0.1:8000/v1"
    assert s.timeout == 45.5
    assert s.max_retries == 3


def test_settings_ocr_prefix_precedence(monkeypatch):
    """Verify that OCR_-prefixed variables take precedence over bare names."""
    monkeypatch.setenv("OCR_BACKEND", "ollama")
    monkeypatch.setenv("BACKEND", "vllm")

    s = Settings.from_env()
    assert s.backend == "ollama"


def test_invalid_backend(monkeypatch):
    """Verify that unsupported backends fail-fast with ValueError."""
    monkeypatch.setenv("OCR_BACKEND", "unsupported-backend")
    with pytest.raises(ValueError, match="Invalid BACKEND"):
        Settings.from_env()


def test_invalid_endpoint(monkeypatch):
    """Verify that endpoints without http:// or https:// fail-fast."""
    monkeypatch.setenv("OCR_ENDPOINT", "ftp://localhost:8080/v1")
    with pytest.raises(ValueError, match="Invalid LOCAL_ENDPOINT"):
        Settings.from_env()


@pytest.mark.parametrize("bad_timeout", ["0", "-10", "abc"])
def test_invalid_timeout(monkeypatch, bad_timeout):
    """Verify non-positive or non-numeric timeout raises ValueError."""
    monkeypatch.setenv("OCR_TIMEOUT", bad_timeout)
    with pytest.raises(ValueError, match="TIMEOUT must be a positive number"):
        Settings.from_env()


@pytest.mark.parametrize("bad_retries", ["-1", "abc"])
def test_invalid_max_retries(monkeypatch, bad_retries):
    """Verify negative or non-integer max_retries raises ValueError."""
    monkeypatch.setenv("OCR_MAX_RETRIES", bad_retries)
    with pytest.raises(ValueError, match="MAX_RETRIES must be a non-negative integer"):
        Settings.from_env()


def test_load_from_custom_env_file(tmp_path, monkeypatch):
    """Verify Settings.from_env can load from a specific file path."""
    for var in [
        "OCR_BACKEND", "BACKEND",
        "OCR_ENDPOINT", "LOCAL_ENDPOINT",
        "OCR_TIMEOUT", "TIMEOUT",
        "OCR_MAX_RETRIES", "MAX_RETRIES",
    ]:
        monkeypatch.delenv(var, raising=False)

    env_file = tmp_path / ".env.test"
    env_file.write_text("OCR_BACKEND=ollama\nOCR_TIMEOUT=99\n", encoding="utf-8")

    s = Settings.from_env(env_path=env_file)
    assert s.backend == "ollama"
    assert s.timeout == 99.0


def test_direct_settings_constructor_validation():
    """Verify Settings(...) constructor enforces __post_init__ validation."""
    with pytest.raises(ValueError, match="Invalid BACKEND"):
        Settings(backend="invalid-backend")

    with pytest.raises(ValueError, match="Invalid LOCAL_ENDPOINT"):
        Settings(local_endpoint="not-an-http-url")

    with pytest.raises(ValueError, match="TIMEOUT must be a positive number"):
        Settings(timeout=-10)

    with pytest.raises(ValueError, match="MAX_RETRIES must be a non-negative integer"):
        Settings(max_retries=-1)

    # Valid direct construction with normalization
    s = Settings(backend="  OLLAMA  ", local_endpoint="http://127.0.0.1:11434/v1/")
    assert s.backend == "ollama"
    assert s.local_endpoint == "http://127.0.0.1:11434/v1"

