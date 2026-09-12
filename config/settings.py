"""Runtime configuration loader for local OCR inference."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional, Set
from urllib.parse import urlsplit
from dotenv import load_dotenv

VALID_BACKENDS: Set[str] = {"llama-cpp", "ollama", "vllm"}
LOOPBACK_HOSTS: Set[str] = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Settings:
    """Application runtime configuration for local model inference.

    Attributes:
        backend: Inference engine backend identifier ('llama-cpp', 'ollama', 'vllm').
        local_endpoint: Base URL endpoint for the OpenAI-compatible vision API.
        timeout: Network request timeout in seconds.
        max_retries: Maximum number of retry attempts upon transient network failure.
        allow_remote: Explicit opt-in flag to permit non-loopback / remote endpoints.
    """

    backend: str = "llama-cpp"
    local_endpoint: str = "http://localhost:8080/v1"
    timeout: float = 60.0
    max_retries: int = 2
    allow_remote: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize configuration attributes across all construction paths."""
        # Allow remote validation
        val_allow_remote = bool(self.allow_remote)
        if isinstance(self.allow_remote, str):
            val_allow_remote = self.allow_remote.strip().lower() in ("1", "true", "yes", "on")
        object.__setattr__(self, "allow_remote", val_allow_remote)

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
        clean_endpoint = self.local_endpoint.strip().rstrip("/")
        if not (clean_endpoint.startswith("http://") or clean_endpoint.startswith("https://")):
            raise ValueError(f"Invalid LOCAL_ENDPOINT: '{self.local_endpoint}'. Must start with 'http://' or 'https://'")

        parsed = urlsplit(clean_endpoint)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValueError(f"Invalid LOCAL_ENDPOINT: '{self.local_endpoint}'. Missing hostname.")

        if not val_allow_remote and hostname not in LOOPBACK_HOSTS:
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

    @property
    def is_loopback(self) -> bool:
        """Determine whether the configured endpoint targets a local loopback address."""
        parsed = urlsplit(self.local_endpoint)
        return (parsed.hostname or "").lower() in LOOPBACK_HOSTS

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
        else:
            load_dotenv()

        backend = os.getenv("OCR_BACKEND") or os.getenv("BACKEND", "llama-cpp")
        endpoint = os.getenv("OCR_ENDPOINT") or os.getenv("LOCAL_ENDPOINT", "http://localhost:8080/v1")
        raw_timeout = os.getenv("OCR_TIMEOUT") or os.getenv("TIMEOUT", "60.0")
        raw_retries = os.getenv("OCR_MAX_RETRIES") or os.getenv("MAX_RETRIES", "2")
        raw_allow_remote = os.getenv("OCR_ALLOW_REMOTE") or os.getenv("ALLOW_REMOTE", "false")
        allow_remote = raw_allow_remote.strip().lower() in ("1", "true", "yes", "on")

        return cls(
            backend=backend,
            local_endpoint=endpoint,
            timeout=raw_timeout,  # type: ignore[arg-type]
            max_retries=raw_retries,  # type: ignore[arg-type]
            allow_remote=allow_remote,
        )

