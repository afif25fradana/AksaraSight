"""Runtime configuration loader for local OCR inference."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional, Set
from dotenv import load_dotenv

VALID_BACKENDS: Set[str] = {"llama-cpp", "ollama", "vllm"}


@dataclass(frozen=True)
class Settings:
    """Application runtime configuration for local model inference.

    Attributes:
        backend: Inference engine backend identifier ('llama-cpp', 'ollama', 'vllm').
        local_endpoint: Base URL endpoint for the OpenAI-compatible vision API.
        timeout: Network request timeout in seconds.
        max_retries: Maximum number of retry attempts upon transient network failure.
    """

    backend: str = "llama-cpp"
    local_endpoint: str = "http://localhost:8080/v1"
    timeout: float = 60.0
    max_retries: int = 2

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

        # Backend validation
        raw_backend = os.getenv("OCR_BACKEND") or os.getenv("BACKEND", "llama-cpp")
        backend = raw_backend.strip().lower()
        if backend not in VALID_BACKENDS:
            valid_list = ", ".join(sorted(VALID_BACKENDS))
            raise ValueError(f"Invalid BACKEND: '{backend}'. Supported backends: {valid_list}")

        # Endpoint validation & normalization
        raw_endpoint = os.getenv("OCR_ENDPOINT") or os.getenv("LOCAL_ENDPOINT", "http://localhost:8080/v1")
        endpoint = raw_endpoint.strip().rstrip("/")
        if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
            raise ValueError(f"Invalid LOCAL_ENDPOINT: '{endpoint}'. Must start with 'http://' or 'https://'")

        # Timeout validation
        raw_timeout = os.getenv("OCR_TIMEOUT") or os.getenv("TIMEOUT", "60")
        try:
            timeout = float(raw_timeout)
            if timeout <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"TIMEOUT must be a positive number, got: '{raw_timeout}'")

        # Max retries validation
        raw_retries = os.getenv("OCR_MAX_RETRIES") or os.getenv("MAX_RETRIES", "2")
        try:
            max_retries = int(raw_retries)
            if max_retries < 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"MAX_RETRIES must be a non-negative integer, got: '{raw_retries}'")

        return cls(
            backend=backend,
            local_endpoint=endpoint,
            timeout=timeout,
            max_retries=max_retries,
        )
