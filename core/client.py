"""Universal OpenAI-compatible vision client for local inference backends.

Provides resilient HTTP communication with local LLM serving engines
(llama-server, Ollama, vLLM) exposing standard OpenAI-compatible Vision endpoints.
"""

from dataclasses import dataclass
import random
import time
from typing import Any, Dict, Optional, Tuple, Union
import requests
from requests.adapters import HTTPAdapter

from config.settings import Settings

# HTTP status codes eligible for exponential backoff retries
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


# ==============================================================================
# Client Exception Hierarchy
# ==============================================================================

class ClientError(Exception):
    """Base exception for all local inference client failures."""


class ServerOfflineError(ClientError):
    """Raised immediately when the local serving backend is unreachable (fail-fast)."""


class ServerTimeoutError(ClientError):
    """Raised when an inference request exceeds the configured network timeout."""


class BadRequestError(ClientError):
    """Raised when the backend rejects the request payload (HTTP 400, fail-fast)."""


class ServerError(ClientError):
    """Raised when the backend returns a server-side error after retry exhaustion."""


class ResponseParsingError(ClientError):
    """Raised when the backend returns an unparseable or schema-violating response body.

    Note:
        Handling for empty/null message content, missing choice dictionaries, and
        unexpected content types is defensive-only (unverified against a live llama-server
        instance). These parsing edge cases are implemented based on llama.cpp source
        inspection and OpenAI specifications, and must be re-validated during Phase 1
        live integration tests once the local backend is online.
    """


# Minimal 1x1 white PNG Data URL for lightweight startup self-test probes (~68 bytes)
_TINY_1X1_PNG_B64 = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# ==============================================================================
# Helper Functions
# ==============================================================================

def resolve_chat_endpoint(endpoint: str) -> str:
    """Normalize a base URL or endpoint to a full chat completions URL.

    Args:
        endpoint: Base or partial URL (e.g. 'http://localhost:8080',
            'http://localhost:8080/v1', or 'http://localhost:8080/v1/chat/completions').

    Returns:
        str: Fully qualified '/v1/chat/completions' endpoint URL.
    """
    cleaned = endpoint.strip().rstrip("/")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/v1/chat/completions"


# ==============================================================================
# VisionClient Implementation
# ==============================================================================

class VisionClient:
    """Universal OpenAI-compatible vision client for local LLM engines.

    Maintains a persistent connection pool via requests.Session, formats vision
    inference requests, and implements full-jitter exponential backoff on transient
    server errors.

    Attributes:
        settings: Application runtime configuration.
        endpoint: Full URL for the chat completions endpoint.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        session: Optional[requests.Session] = None,
        backoff_factor: float = 0.5,
    ) -> None:
        """Initialize the VisionClient.

        Args:
            settings: Runtime settings. Defaults to Settings() if omitted.
            session: Optional custom or mocked requests.Session instance.
            backoff_factor: Base multiplier for full-jitter exponential backoff.
        """
        self.settings = settings or Settings()
        self.endpoint = resolve_chat_endpoint(self.settings.local_endpoint)
        self.backoff_factor = backoff_factor

        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._session = requests.Session()
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
            self._owns_session = True

    def close(self) -> None:
        """Close the underlying HTTP session if owned by this client."""
        if self._owns_session and self._session is not None:
            self._session.close()

    def __enter__(self) -> "VisionClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def complete(
        self,
        image_b64: str,
        prompt: str = "Text Recognition:",
        model: str = "glm-ocr",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Tuple[str, Dict[str, Any], float]:
        """Send a single page image and prompt to the local vision backend.

        Args:
            image_b64: RFC-2397 base64 Data URL string ('data:image/...;base64,...').
            prompt: Text prompt / instruction for the model.
            model: Model identifier tag passed to the OpenAI API endpoint.
            max_tokens: Maximum tokens to generate (default: 4096, justified by
                GLM-OCR 128k context and page density).
            temperature: Sampling temperature (default: 0.0 for deterministic OCR).

        Returns:
            Tuple[str, Dict[str, Any], float]:
                - markdown_text: Extracted text or markdown transcribed by the model.
                - raw_json: Complete deserialized JSON response dictionary.
                - latency_seconds: Wall-clock request execution time in seconds.

        Raises:
            ServerOfflineError: If connection to the local backend fails (fail-fast).
            ServerTimeoutError: If the request exceeds settings.timeout.
            BadRequestError: If backend responds with HTTP 400 (malformed payload).
            ServerError: If backend returns 5xx or 429 after retries are exhausted.
            ResponseParsingError: If backend returns invalid JSON or schema violations.
        """
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_b64}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {"Content-Type": "application/json"}
        max_retries = max(0, self.settings.max_retries)
        last_error_status: Optional[int] = None
        last_error_text: str = ""

        for attempt in range(max_retries + 1):
            start_time = time.perf_counter()
            try:
                response = self._session.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=self.settings.timeout,
                )
            except requests.exceptions.Timeout as exc:
                raise ServerTimeoutError(
                    f"Request to '{self.endpoint}' timed out after {self.settings.timeout:.1f}s."
                ) from exc
            except requests.exceptions.ConnectionError as exc:
                raise ServerOfflineError(
                    f"Cannot connect to local backend at '{self.endpoint}'. "
                    "Ensure llama-server or Ollama is running."
                ) from exc
            except requests.exceptions.RequestException as exc:
                raise ClientError(f"HTTP request to '{self.endpoint}' failed: {exc}") from exc

            latency = time.perf_counter() - start_time

            # Success path
            if response.status_code == 200:
                return self._parse_response(response, latency)

            # Client error: HTTP 400 Bad Request (fail-fast, do not retry)
            if response.status_code == 400:
                snippet = response.text[:200]
                raise BadRequestError(
                    f"Local backend rejected request (HTTP 400): {snippet}"
                )

            # Retryable server errors
            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error_status = response.status_code
                last_error_text = response.text[:200]
                if attempt < max_retries:
                    # Full-jitter exponential backoff: sleep in [0, backoff_factor * 2^attempt]
                    max_sleep = self.backoff_factor * (2 ** attempt)
                    sleep_time = random.uniform(0, max_sleep)
                    time.sleep(sleep_time)
                    continue

            # Non-retryable error or retry exhaustion
            snippet = response.text[:200]
            raise ServerError(
                f"Local backend returned HTTP {response.status_code}: {snippet}"
            )

        raise ServerError(
            f"Local backend failed after {max_retries} retries (HTTP {last_error_status}): {last_error_text}"
        )

    def verify_multimodal_support(self) -> None:
        """Send a lightweight 1x1 test image probe to verify backend multimodal support.

        Verifies that the inference server is running, accepting OpenAI-compatible
        chat completions requests, and has a multimodal vision projector loaded.

        Raises:
            ServerOfflineError: If the server is offline or unreachable.
            ClientError: If the server rejects image input or fails the probe.
        """
        try:
            text, _, _ = self.complete(_TINY_1X1_PNG_B64, prompt="OCR:", max_tokens=16)
            if text is None:
                raise ClientError("Backend returned null content during multimodal self-test probe.")
        except ServerOfflineError:
            raise
        except ClientError as exc:
            err_str = str(exc).lower()
            if "mmproj" in err_str or "image input is not supported" in err_str:
                raise ClientError(
                    "Backend not responding correctly to image input. "
                    "Ensure the inference server was launched with multimodal vision projector support (--mmproj)."
                ) from exc
            raise ClientError(f"Backend not responding correctly to image input: {exc}") from exc

    def _parse_response(
        self,
        response: requests.Response,
        latency: float,
    ) -> Tuple[str, Dict[str, Any], float]:
        """Parse and validate OpenAI-compatible chat completion JSON response.

        Note:
            Parsing edge cases (such as None content, missing choices, or non-string
            content fields) are implemented defensively (unverified against live llama-server)
            and must be re-validated during integration testing.
        """
        try:
            data = response.json()
        except Exception as exc:
            raise ResponseParsingError(
                f"Failed to parse JSON response from '{self.endpoint}': {response.text[:200]}"
            ) from exc

        if not isinstance(data, dict):
            raise ResponseParsingError(
                f"Expected JSON object in response body, got {type(data).__name__}"
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            data_repr = str(data)
            snippet = data_repr[:250] + ("..." if len(data_repr) > 250 else "")
            raise ResponseParsingError(
                f"Response missing non-empty 'choices' array: {snippet}"
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise ResponseParsingError(
                f"Expected 'choice' element to be dict, got {type(first_choice).__name__}"
            )

        message = first_choice.get("message")
        if not isinstance(message, dict):
            choice_repr = str(first_choice)
            snippet = choice_repr[:250] + ("..." if len(choice_repr) > 250 else "")
            raise ResponseParsingError(
                f"Choice missing 'message' dictionary: {snippet}"
            )

        content = message.get("content")
        if content is None:
            raise ResponseParsingError("Model returned null/empty content in message")
        elif isinstance(content, str):
            text = content.strip()
        else:
            raise ResponseParsingError(
                f"Expected string content in message, got {type(content).__name__}"
            )

        return text, data, latency
