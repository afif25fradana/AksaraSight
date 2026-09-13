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
    assert s.is_loopback is True
    assert s.allow_remote is False


@pytest.mark.parametrize(
    "loopback_url",
    [
        "http://localhost:8080/v1",
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8080/v1",
    ],
)
def test_loopback_hosts_allowed_by_default(loopback_url):
    """Verify loopback addresses pass validation by default."""
    s = Settings(local_endpoint=loopback_url)
    assert s.is_loopback is True


@pytest.mark.parametrize(
    "remote_url",
    [
        "http://0.0.0.0:8080/v1",
        "http://api.openai.com/v1",
        "https://external-cloud.com/v1",
        "http://192.168.1.50:8080/v1",
        "http://10.0.0.1:8080/v1",
    ],
)
def test_remote_endpoint_fails_fast_by_default(remote_url):
    """Verify non-loopback endpoints raise ValueError fail-fast when allow_remote is False."""
    with pytest.raises(ValueError, match="Security violation: Non-loopback endpoint"):
        Settings(local_endpoint=remote_url)


def test_remote_endpoint_allowed_with_explicit_opt_in():
    """Verify non-loopback endpoint passes when allow_remote=True is explicitly set."""
    s = Settings(local_endpoint="http://192.168.1.50:8080/v1", allow_remote=True)
    assert s.local_endpoint == "http://192.168.1.50:8080/v1"
    assert s.allow_remote is True
    assert s.is_loopback is False


@pytest.mark.parametrize("env_val", ["1", "true", "True", "yes", "YES", "on"])
def test_remote_endpoint_allowed_via_env_var(monkeypatch, env_val):
    """Verify OCR_ALLOW_REMOTE permits non-loopback endpoints via environment variable."""
    monkeypatch.setenv("OCR_ENDPOINT", "http://192.168.1.100:8080/v1")
    monkeypatch.setenv("OCR_ALLOW_REMOTE", env_val)

    s = Settings.from_env()
    assert s.allow_remote is True
    assert s.is_loopback is False
    assert s.local_endpoint == "http://192.168.1.100:8080/v1"


def test_remote_endpoint_rejected_via_env_var_when_not_opted_in(monkeypatch):
    """Verify non-loopback endpoint in env raises ValueError when OCR_ALLOW_REMOTE is not set."""
    monkeypatch.setenv("OCR_ENDPOINT", "http://evil-server.com/v1")
    monkeypatch.delenv("OCR_ALLOW_REMOTE", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE", raising=False)

    with pytest.raises(ValueError, match="Security violation: Non-loopback endpoint"):
        Settings.from_env()


def test_new_settings_fields_defaults():
    """Verify default values for Stage A settings additions."""
    s = Settings()
    assert s.llama_server_path is None
    assert s.model_repo == "ggml-org/GLM-OCR-GGUF"
    assert s.auto_start_server is False
    assert s.dpi == 100
    assert s.max_pages is None


@pytest.mark.parametrize("bad_dpi", [0, -10, "abc"])
def test_dpi_validation(bad_dpi):
    """Verify DPI must be a positive integer."""
    with pytest.raises(ValueError, match="DPI must be a positive integer"):
        Settings(dpi=bad_dpi)


@pytest.mark.parametrize("valid_dpi", [72, 100, 150, "200"])
def test_dpi_valid(valid_dpi):
    """Verify valid DPI values are cast to int."""
    s = Settings(dpi=valid_dpi)
    assert s.dpi == int(valid_dpi)


@pytest.mark.parametrize("bad_pages", [0, -1, "invalid"])
def test_max_pages_validation(bad_pages):
    """Verify MAX_PAGES must be a positive integer or None."""
    with pytest.raises(ValueError, match="MAX_PAGES must be a positive integer or None"):
        Settings(max_pages=bad_pages)


def test_max_pages_valid():
    """Verify valid max_pages values are cast to int or preserved as None."""
    assert Settings(max_pages=None).max_pages is None
    assert Settings(max_pages=10).max_pages == 10
    assert Settings(max_pages="5").max_pages == 5


@pytest.mark.parametrize("bad_repo", ["", "   ", None])
def test_model_repo_validation(bad_repo):
    """Verify model_repo must be a non-empty string."""
    with pytest.raises(ValueError, match="MODEL_REPO must be a non-empty string"):
        Settings(model_repo=bad_repo)


@pytest.mark.parametrize("val, expected", [
    (True, True),
    (False, False),
    ("1", True),
    ("true", True),
    ("yes", True),
    ("on", True),
    ("0", False),
    ("false", False),
    ("no", False),
])
def test_auto_start_server_coercion(val, expected):
    """Verify auto_start_server string values are properly coerced."""
    s = Settings(auto_start_server=val)
    assert s.auto_start_server is expected


def test_save_to_env_creates_and_roundtrips(tmp_path, monkeypatch):
    """Verify save_to_env creates a valid .env and Settings.from_env loads it accurately."""
    env_file = tmp_path / "test.env"

    settings = Settings(
        backend="ollama",
        local_endpoint="http://localhost:11434/v1",
        timeout=45.0,
        max_retries=3,
        allow_remote=False,
        llama_server_path=r"C:\custom\llama-server.exe",
        model_repo="custom/ocr-model",
        auto_start_server=True,
        dpi=150,
        max_pages=25,
    )

    saved_path = settings.save_to_env(env_file)
    assert saved_path.is_file()

    # Clear environment variables to force loading directly from the file
    for k in [
        "OCR_BACKEND", "BACKEND", "OCR_ENDPOINT", "LOCAL_ENDPOINT",
        "OCR_TIMEOUT", "TIMEOUT", "OCR_MAX_RETRIES", "MAX_RETRIES",
        "OCR_ALLOW_REMOTE", "ALLOW_REMOTE", "OCR_LLAMA_SERVER_PATH",
        "LLAMA_SERVER_PATH", "OCR_MODEL_REPO", "MODEL_REPO",
        "OCR_AUTO_START_SERVER", "AUTO_START_SERVER", "OCR_DPI", "DPI",
        "OCR_MAX_PAGES", "MAX_PAGES",
    ]:
        monkeypatch.delenv(k, raising=False)

    loaded = Settings.from_env(env_path=env_file)
    assert loaded.backend == "ollama"
    assert loaded.local_endpoint == "http://localhost:11434/v1"
    assert loaded.timeout == 45.0
    assert loaded.max_retries == 3
    assert loaded.allow_remote is False
    assert loaded.llama_server_path == r"C:\custom\llama-server.exe"
    assert loaded.model_repo == "custom/ocr-model"
    assert loaded.auto_start_server is True
    assert loaded.dpi == 150
    assert loaded.max_pages == 25


def test_save_to_env_preserves_comments_and_unrelated_vars(tmp_path):
    """Verify save_to_env updates existing keys in place without wiping comments or other keys."""
    env_file = tmp_path / "existing.env"
    initial_content = (
        "# Custom Application Configuration\n"
        "MY_CUSTOM_VAR=keep_me\n"
        "\n"
        "# Local backend endpoint\n"
        "OCR_ENDPOINT=http://localhost:8080/v1\n"
        "OCR_TIMEOUT=30\n"
    )
    env_file.write_text(initial_content, encoding="utf-8")

    settings = Settings(
        local_endpoint="http://localhost:9000/v1",
        timeout=90.0,
        dpi=120,
    )
    settings.save_to_env(env_file)

    result_content = env_file.read_text(encoding="utf-8")
    assert "# Custom Application Configuration" in result_content
    assert "MY_CUSTOM_VAR=keep_me" in result_content
    assert "OCR_ENDPOINT=http://localhost:9000/v1" in result_content
    assert "OCR_TIMEOUT=90.0" in result_content
    assert "OCR_DPI=120" in result_content



