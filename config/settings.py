"""Runtime configuration loader for local OCR inference."""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import sys
from typing import Any, Optional, Set, overload
from urllib.parse import urlsplit
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

VALID_BACKENDS: Set[str] = {"llama-cpp", "ollama", "vllm"}
VALID_RUNTIME_MODES: Set[str] = {"managed", "custom"}
VALID_MANAGED_BACKENDS: Set[str] = {"auto", "cuda", "vulkan", "cpu"}
LOOPBACK_HOSTS: Set[str] = {"localhost", "127.0.0.1", "::1"}


def _resolve_default_env_path() -> Path:
    """Resolve the default .env path based on whether running frozen or from source.

    If frozen (PyInstaller executable), defaults to '.env' adjacent to the executable.
    If running from source, defaults to '.env' in the current working directory.
    """
    if getattr(sys, "frozen", False):
        exe_env = Path(sys.executable).parent / ".env"
        return exe_env
    return Path(".env")


def _to_bool(val: Any) -> bool:
    """Normalize boolean or string representation to a boolean."""
    return val.strip().lower() in ("1", "true", "yes", "on") if isinstance(val, str) else bool(val)


@overload
def _get_env_with_fallback(canonical_key: str, legacy_key: str, default: str) -> str: ...


@overload
def _get_env_with_fallback(canonical_key: str, legacy_key: str, default: None = None) -> Optional[str]: ...


def _get_env_with_fallback(canonical_key: str, legacy_key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve environment variable, logging deprecation warning if legacy key is used."""
    val = os.getenv(canonical_key)
    if val is not None and val != "":
        return val
    legacy_val = os.getenv(legacy_key)
    if legacy_val is not None and legacy_val != "":
        logger.warning(
            "Legacy environment variable '%s' is deprecated; please use '%s'",
            legacy_key,
            canonical_key,
        )
        return legacy_val
    return default


@dataclass(frozen=True)
class Settings:
    """Application runtime configuration for local model inference.

    Attributes:
        backend: Inference engine backend identifier ('llama-cpp', 'ollama', 'vllm').
        local_endpoint: Base URL endpoint for the OpenAI-compatible vision API.
        timeout: Network request timeout in seconds.
        max_retries: Maximum number of retry attempts upon transient network failure.
        allow_remote: Explicit opt-in flag to permit non-loopback / remote endpoints.
        runtime_mode: Binary management mode ('managed' for auto-download, 'custom' for manual path).
        managed_backend_override: Acceleration backend override for managed runtime ('auto', 'cuda', 'vulkan', 'cpu').
    """

    backend: str = "llama-cpp"
    local_endpoint: str = "http://localhost:8080/v1"
    timeout: float = 60.0
    max_retries: int = 2
    allow_remote: bool = False
    runtime_mode: str = "custom"
    managed_backend_override: str = "auto"
    llama_server_path: Optional[str] = None
    model_repo: str = "ggml-org/GLM-OCR-GGUF"
    auto_start_server: bool = False
    dpi: int = 100
    max_pages: Optional[int] = None
    max_image_dimension: int = 2048

    def __post_init__(self) -> None:
        """Validate and normalize configuration attributes across all construction paths."""
        # Allow remote validation
        object.__setattr__(self, "allow_remote", _to_bool(self.allow_remote))

        # Runtime mode validation & normalization
        if not isinstance(self.runtime_mode, str):
            raise ValueError(f"RUNTIME_MODE must be a string, got: '{self.runtime_mode}'")
        clean_runtime_mode = self.runtime_mode.strip().lower()
        if clean_runtime_mode not in VALID_RUNTIME_MODES:
            valid_modes = ", ".join(sorted(VALID_RUNTIME_MODES))
            raise ValueError(f"Invalid RUNTIME_MODE: '{self.runtime_mode}'. Must be one of: {valid_modes}")
        object.__setattr__(self, "runtime_mode", clean_runtime_mode)

        # Managed backend override validation & normalization
        if not isinstance(self.managed_backend_override, str):
            raise ValueError(f"MANAGED_BACKEND_OVERRIDE must be a string, got: '{self.managed_backend_override}'")
        clean_backend_override = self.managed_backend_override.strip().lower()
        if clean_backend_override not in VALID_MANAGED_BACKENDS:
            valid_backends = ", ".join(sorted(VALID_MANAGED_BACKENDS))
            raise ValueError(
                f"Invalid MANAGED_BACKEND_OVERRIDE: '{self.managed_backend_override}'. Must be one of: {valid_backends}"
            )
        object.__setattr__(self, "managed_backend_override", clean_backend_override)

        # Backend validation & normalization
        if not isinstance(self.backend, str):
            raise ValueError(f"BACKEND must be a string, got: '{self.backend}'")
        clean_backend = self.backend.strip().lower()
        if clean_backend not in VALID_BACKENDS:
            valid_list = ", ".join(sorted(VALID_BACKENDS))
            raise ValueError(f"Invalid BACKEND: '{self.backend}'. Supported backends: {valid_list}")
        object.__setattr__(self, "backend", clean_backend)

        # Endpoint validation & normalization
        if not isinstance(self.local_endpoint, str):
            raise ValueError(f"LOCAL_ENDPOINT must be a string, got: '{self.local_endpoint}'")
        clean_endpoint = self.local_endpoint.strip().replace("\r", "").replace("\n", "").rstrip("/")
        if not (clean_endpoint.startswith("http://") or clean_endpoint.startswith("https://")):
            raise ValueError(f"Invalid LOCAL_ENDPOINT: '{self.local_endpoint}'. Must start with 'http://' or 'https://'")

        parsed = urlsplit(clean_endpoint)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValueError(f"Invalid LOCAL_ENDPOINT: '{self.local_endpoint}'. Missing hostname.")

        try:
            port = parsed.port
            if port is not None and not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            raise ValueError(f"Invalid LOCAL_ENDPOINT port: '{clean_endpoint}'. Port must be between 1 and 65535.")

        if not self.allow_remote and hostname not in LOOPBACK_HOSTS:
            raise ValueError(
                f"Security violation: Non-loopback endpoint '{clean_endpoint}' is not permitted by default "
                "to prevent data exfiltration. Configure a local backend (localhost/127.0.0.1) or explicitly "
                "allow remote endpoints via allow_remote=True (or OCR_ALLOW_REMOTE=1 / --allow-remote)."
            )

        object.__setattr__(self, "local_endpoint", clean_endpoint)

        # Timeout validation
        try:
            val_timeout = float(self.timeout)
            if val_timeout <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"TIMEOUT must be a positive number, got: '{self.timeout}'")
        object.__setattr__(self, "timeout", val_timeout)

        # Max retries validation
        try:
            val_retries = int(self.max_retries)
            if val_retries < 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"MAX_RETRIES must be a non-negative integer, got: '{self.max_retries}'")
        object.__setattr__(self, "max_retries", val_retries)

        # Server binary path normalization
        if self.llama_server_path is not None:
            clean_path = str(self.llama_server_path).strip().replace("\r", "").replace("\n", "")
            object.__setattr__(self, "llama_server_path", clean_path if clean_path else None)

        # Model repository validation
        if not isinstance(self.model_repo, str) or not self.model_repo.strip():
            raise ValueError(f"MODEL_REPO must be a non-empty string, got: '{self.model_repo}'")
        clean_repo = self.model_repo.strip().replace("\r", "").replace("\n", "")
        if not clean_repo:
            raise ValueError(f"MODEL_REPO must not be empty, got: '{self.model_repo}'")
        object.__setattr__(self, "model_repo", clean_repo)

        # Auto-start server validation
        object.__setattr__(self, "auto_start_server", _to_bool(self.auto_start_server))

        # DPI validation
        try:
            val_dpi = int(self.dpi)
            if val_dpi <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"DPI must be a positive integer, got: '{self.dpi}'")
        object.__setattr__(self, "dpi", val_dpi)

        # Max pages validation
        if self.max_pages is not None:
            try:
                val_max_pages = int(self.max_pages)
                if val_max_pages <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError(f"MAX_PAGES must be a positive integer or None, got: '{self.max_pages}'")
            object.__setattr__(self, "max_pages", val_max_pages)

        # Max image dimension validation
        try:
            val_dim = int(self.max_image_dimension)
            if not (512 <= val_dim <= 8192):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(
                f"MAX_IMAGE_DIMENSION must be an integer between 512 and 8192, got: '{self.max_image_dimension}'"
            )
        object.__setattr__(self, "max_image_dimension", val_dim)

    @property
    def is_loopback(self) -> bool:
        """Determine whether the configured endpoint targets a local loopback address."""
        parsed = urlsplit(self.local_endpoint)
        return (parsed.hostname or "").lower() in LOOPBACK_HOSTS

    @property
    def effective_llama_server_path(self) -> Optional[str]:
        """Resolve the effective llama-server binary path based on runtime_mode.

        In 'custom' mode: returns the configured manual path (llama_server_path).
        In 'managed' mode: resolves the target backend (override or cached hardware profile)
        and retrieves the verified managed binary path from disk.

        Returns:
            Optional[str]: Absolute path string to the executable, or None if unconfigured/uninstalled.
        """
        if self.runtime_mode == "custom":
            return self.llama_server_path

        # Managed mode
        backend = self.managed_backend_override
        if backend == "auto":
            from core.hardware import get_cached_hardware_profile

            profile = get_cached_hardware_profile()
            backend = profile.recommended_backend

        from core.runtime_manager import get_installed_runtime_path

        installed_path = get_installed_runtime_path(backend=backend)
        return str(installed_path) if installed_path is not None else None

    @classmethod
    def from_env(cls, env_path: Optional[str | Path] = None) -> "Settings":
        """Load and validate settings from environment variables and .env file.

        Prioritizes 'OCR_'-prefixed environment variables, with fallback to
        standard names (e.g., OCR_BACKEND -> BACKEND).

        Args:
            env_path: Optional file path to a specific .env file.

        Returns:
            Settings: An immutable, validated configuration instance.

        Raises:
            ValueError: If any setting fails validation or has an invalid type/range.
        """
        if env_path is not None:
            load_dotenv(dotenv_path=env_path)
        elif getattr(sys, "frozen", False):
            default_env = _resolve_default_env_path()
            if default_env.is_file():
                load_dotenv(dotenv_path=default_env)
            else:
                load_dotenv()
        else:
            load_dotenv()

        backend = _get_env_with_fallback("OCR_BACKEND", "BACKEND", "llama-cpp")
        endpoint = _get_env_with_fallback("OCR_ENDPOINT", "LOCAL_ENDPOINT", "http://localhost:8080/v1")
        raw_timeout = _get_env_with_fallback("OCR_TIMEOUT", "TIMEOUT", "60.0")
        raw_retries = _get_env_with_fallback("OCR_MAX_RETRIES", "MAX_RETRIES", "2")
        allow_remote = _to_bool(_get_env_with_fallback("OCR_ALLOW_REMOTE", "ALLOW_REMOTE", "false"))

        raw_llama_path = _get_env_with_fallback("OCR_LLAMA_SERVER_PATH", "LLAMA_SERVER_PATH")
        raw_runtime_mode = _get_env_with_fallback("OCR_RUNTIME_MODE", "RUNTIME_MODE")
        if raw_runtime_mode is not None and raw_runtime_mode.strip():
            runtime_mode = raw_runtime_mode.strip().lower()
        else:
            # Backward compatibility rule: if a custom path is already configured in env, default to custom.
            # New installs without a configured path default to managed.
            runtime_mode = "custom" if (raw_llama_path and raw_llama_path.strip()) else "managed"

        raw_backend_override = _get_env_with_fallback("OCR_MANAGED_BACKEND_OVERRIDE", "MANAGED_BACKEND_OVERRIDE", "auto")
        managed_backend_override = raw_backend_override.strip().lower() if raw_backend_override else "auto"

        model_repo = _get_env_with_fallback("OCR_MODEL_REPO", "MODEL_REPO", "ggml-org/GLM-OCR-GGUF")
        auto_start = _to_bool(_get_env_with_fallback("OCR_AUTO_START_SERVER", "AUTO_START_SERVER", "false"))

        raw_dpi = _get_env_with_fallback("OCR_DPI", "DPI", "100")
        raw_max_pages = _get_env_with_fallback("OCR_MAX_PAGES", "MAX_PAGES")
        max_pages = int(raw_max_pages.strip()) if raw_max_pages and str(raw_max_pages).strip() else None

        raw_max_dim = _get_env_with_fallback("OCR_MAX_IMAGE_DIMENSION", "MAX_IMAGE_DIMENSION", "2048")

        return cls(
            backend=backend,
            local_endpoint=endpoint,
            timeout=raw_timeout,  # type: ignore[arg-type]  # string from env validated and cast to float in __post_init__
            max_retries=raw_retries,  # type: ignore[arg-type]  # string from env validated and cast to int in __post_init__
            allow_remote=allow_remote,
            runtime_mode=runtime_mode,
            managed_backend_override=managed_backend_override,
            llama_server_path=raw_llama_path,
            model_repo=model_repo,
            auto_start_server=auto_start,
            dpi=raw_dpi,  # type: ignore[arg-type]  # string from env validated and cast to int in __post_init__
            max_pages=max_pages,
            max_image_dimension=raw_max_dim,  # type: ignore[arg-type]  # string from env validated and cast to int in __post_init__
        )

    def save_to_env(self, env_path: Optional[str | Path] = None) -> Path:
        """Persist current settings to a .env file, preserving comments and formatting.

        Args:
            env_path: Target .env file path. Defaults to '.env' in the current working directory.

        Returns:
            Path: The resolved path of the updated .env file.
        """
        if env_path is not None:
            target = Path(env_path).resolve()
        else:
            target = _resolve_default_env_path().resolve()

        # Key mapping of managed settings
        managed: dict[str, str] = {
            "OCR_BACKEND": self.backend,
            "OCR_ENDPOINT": self.local_endpoint,
            "OCR_TIMEOUT": str(self.timeout),
            "OCR_MAX_RETRIES": str(self.max_retries),
            "OCR_ALLOW_REMOTE": "true" if self.allow_remote else "false",
            "OCR_RUNTIME_MODE": self.runtime_mode,
            "OCR_MANAGED_BACKEND_OVERRIDE": self.managed_backend_override,
            "OCR_DPI": str(self.dpi),
            "OCR_MAX_PAGES": str(self.max_pages) if self.max_pages is not None else "",
            "OCR_MAX_IMAGE_DIMENSION": str(self.max_image_dimension),
            "OCR_LLAMA_SERVER_PATH": self.llama_server_path or "",
            "OCR_MODEL_REPO": self.model_repo,
            "OCR_AUTO_START_SERVER": "true" if self.auto_start_server else "false",
        }

        # Also track legacy/unprefixed alias mappings
        aliases: dict[str, str] = {
            "BACKEND": "OCR_BACKEND",
            "LOCAL_ENDPOINT": "OCR_ENDPOINT",
            "TIMEOUT": "OCR_TIMEOUT",
            "MAX_RETRIES": "OCR_MAX_RETRIES",
            "ALLOW_REMOTE": "OCR_ALLOW_REMOTE",
            "RUNTIME_MODE": "OCR_RUNTIME_MODE",
            "MANAGED_BACKEND_OVERRIDE": "OCR_MANAGED_BACKEND_OVERRIDE",
            "DPI": "OCR_DPI",
            "MAX_PAGES": "OCR_MAX_PAGES",
            "MAX_IMAGE_DIMENSION": "OCR_MAX_IMAGE_DIMENSION",
            "LLAMA_SERVER_PATH": "OCR_LLAMA_SERVER_PATH",
            "MODEL_REPO": "OCR_MODEL_REPO",
            "AUTO_START_SERVER": "OCR_AUTO_START_SERVER",
        }

        def _quote_val(v: str) -> str:
            # Single-quote strings to preserve whitespace, '#' symbols, and special characters
            # without triggering backslash escape expansion on Windows paths.
            escaped = v.replace("'", "\\'")
            return f"'{escaped}'"

        written_keys: Set[str] = set()
        new_lines: list[str] = []

        if target.is_file():
            content = target.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    new_lines.append(line)
                    continue

                if "=" in line:
                    key_part, _ = line.split("=", 1)
                    key = key_part.strip()
                    canonical_key = aliases.get(key, key)
                    if canonical_key in managed:
                        new_lines.append(f"{key}={_quote_val(managed[canonical_key])}")
                        written_keys.add(canonical_key)
                        continue

                new_lines.append(line)

        # Append any managed keys that were not present in the existing file
        unwritten = [k for k in managed if k not in written_keys]
        if unwritten:
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            for k in unwritten:
                new_lines.append(f"{k}={_quote_val(managed[k])}")

        # Atomic write
        temp_file = target.with_suffix(".env.tmp")
        temp_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        temp_file.replace(target)

        # Synchronize os.environ so in-process environment readers see new values
        for k, v in managed.items():
            os.environ[k] = v

        return target


