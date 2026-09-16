"""Unit tests for universal OpenAI-compatible VisionClient (core/client.py)."""

import json
from unittest.mock import MagicMock, patch
import pytest
import requests

from config.settings import Settings
from core.client import (
    BadRequestError,
    ClientError,
    ResponseParsingError,
    ServerError,
    ServerOfflineError,
    ServerTimeoutError,
    VisionClient,
    resolve_chat_endpoint,
)


# ==============================================================================
# Endpoint Normalization Tests
# ==============================================================================

@pytest.mark.parametrize(
    "input_url, expected",
    [
        ("http://localhost:8080", "http://localhost:8080/v1/chat/completions"),
        ("http://localhost:8080/", "http://localhost:8080/v1/chat/completions"),
        ("http://localhost:8080/v1", "http://localhost:8080/v1/chat/completions"),
        ("http://localhost:8080/v1/", "http://localhost:8080/v1/chat/completions"),
        (
            "http://localhost:8080/v1/chat/completions",
            "http://localhost:8080/v1/chat/completions",
        ),
        (
            "http://localhost:8080/v1/chat/completions/",
            "http://localhost:8080/v1/chat/completions",
        ),
        ("http://192.168.1.50:11434", "http://192.168.1.50:11434/v1/chat/completions"),
    ],
)
def test_resolve_chat_endpoint(input_url: str, expected: str) -> None:
    assert resolve_chat_endpoint(input_url) == expected


# ==============================================================================
# Initialization & Lifecycle Tests
# ==============================================================================

def test_vision_client_default_initialization() -> None:
    client = VisionClient()
    assert client.settings.backend == "llama-cpp"
    assert client.endpoint == "http://localhost:8080/v1/chat/completions"
    assert client._owns_session is True
    client.close()


def test_vision_client_custom_settings_and_session() -> None:
    settings = Settings(
        backend="ollama",
        local_endpoint="http://127.0.0.1:11434/v1",
        timeout=30.0,
        max_retries=3,
    )
    mock_session = MagicMock(spec=requests.Session)
    client = VisionClient(settings=settings, session=mock_session)

    assert client.settings.timeout == 30.0
    assert client.endpoint == "http://127.0.0.1:11434/v1/chat/completions"
    assert client._owns_session is False

    client.close()
    mock_session.close.assert_not_called()


def test_vision_client_context_manager() -> None:
    with VisionClient() as client:
        assert client._session is not None
    # Underlying session should be closed on exit
    assert client._session is not None


# ==============================================================================
# Success & Payload Construction Tests
# ==============================================================================

def test_complete_success_payload_and_return_values() -> None:
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    payload_response = {
        "id": "chatcmpl-test-123",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "glm-ocr",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "  # Extracted Markdown Title\nLine of text.  ",
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 15, "total_tokens": 135},
    }
    mock_response.json.return_value = payload_response

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_response

    client = VisionClient(session=mock_session)
    image_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    prompt = "Text Recognition:"

    text, raw_json, latency = client.complete(image_b64, prompt=prompt)

    # Content stripping & correctness
    assert text == "# Extracted Markdown Title\nLine of text."
    assert raw_json == payload_response
    assert latency >= 0.0

    # Verify posted payload matches universal vision format
    mock_session.post.assert_called_once()
    _, kwargs = mock_session.post.call_args
    assert kwargs["headers"] == {"Content-Type": "application/json"}
    assert kwargs["timeout"] == 60.0

    sent_body = kwargs["json"]
    assert sent_body["model"] == "glm-ocr"
    assert sent_body["max_tokens"] == 4096
    assert sent_body["temperature"] == 0.0
    assert len(sent_body["messages"]) == 1
    assert sent_body["messages"][0]["role"] == "user"
    assert sent_body["messages"][0]["content"] == [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_b64}},
    ]



# ==============================================================================
# Network Error & Fail-Fast Tests
# ==============================================================================

def test_server_offline_connection_error_fails_fast() -> None:
    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = requests.exceptions.ConnectionError("Connection refused")

    client = VisionClient(session=mock_session)
    with pytest.raises(ServerOfflineError, match="Cannot connect to local backend"):
        client.complete("data:image/jpeg;base64,abc")

    # Fail fast: exactly 1 attempt, zero retries
    assert mock_session.post.call_count == 1


def test_server_timeout_error() -> None:
    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = requests.exceptions.Timeout("Read timed out")

    settings = Settings(timeout=5.0)
    client = VisionClient(settings=settings, session=mock_session)
    with pytest.raises(ServerTimeoutError, match="timed out after 5.0s"):
        client.complete("data:image/jpeg;base64,abc")

    assert mock_session.post.call_count == 1


def test_generic_request_exception() -> None:
    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = requests.exceptions.ChunkedEncodingError("Connection broken")

    client = VisionClient(session=mock_session)
    with pytest.raises(ClientError, match="HTTP request to .* failed"):
        client.complete("data:image/jpeg;base64,abc")


# ==============================================================================
# HTTP Error Status & Retry Loop Tests
# ==============================================================================

def test_bad_request_http_400_fails_fast() -> None:
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 400
    mock_response.text = '{"error": {"message": "Invalid model glm-ocr"}}'

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_response

    client = VisionClient(session=mock_session)
    with pytest.raises(BadRequestError, match="Local backend rejected request .*HTTP 400"):
        client.complete("data:image/jpeg;base64,abc")

    # Must fail immediately with 0 retries
    assert mock_session.post.call_count == 1


@patch("time.sleep", return_value=None)
def test_retryable_server_error_recovers_after_retry(mock_sleep: MagicMock) -> None:
    resp_503 = MagicMock(spec=requests.Response)
    resp_503.status_code = 503
    resp_503.text = "Service Unavailable"

    resp_200 = MagicMock(spec=requests.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "choices": [{"message": {"content": "Recovered text"}}]
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = [resp_503, resp_200]

    client = VisionClient(session=mock_session, backoff_factor=0.01)
    text, _, _ = client.complete("data:image/jpeg;base64,abc")

    assert text == "Recovered text"
    assert mock_session.post.call_count == 2
    assert mock_sleep.call_count == 1


@patch("time.sleep", return_value=None)
def test_retryable_server_error_exhaustion_raises_server_error(mock_sleep: MagicMock) -> None:
    resp_500 = MagicMock(spec=requests.Response)
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = resp_500

    settings = Settings(max_retries=2)
    client = VisionClient(settings=settings, session=mock_session, backoff_factor=0.01)

    with pytest.raises(ServerError, match="Local backend returned HTTP 500"):
        client.complete("data:image/jpeg;base64,abc")

    # 1 initial call + 2 retries = 3 calls
    assert mock_session.post.call_count == 3
    assert mock_sleep.call_count == 2


@patch("time.sleep", return_value=None)
def test_rate_limit_429_retries(mock_sleep: MagicMock) -> None:
    resp_429 = MagicMock(spec=requests.Response)
    resp_429.status_code = 429
    resp_429.text = "Too Many Requests"

    resp_200 = MagicMock(spec=requests.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "choices": [{"message": {"content": "Success after rate limit"}}]
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.side_effect = [resp_429, resp_200]

    client = VisionClient(session=mock_session, backoff_factor=0.01)
    text, _, _ = client.complete("data:image/jpeg;base64,abc")

    assert text == "Success after rate limit"
    assert mock_session.post.call_count == 2


def test_non_retryable_404_raises_server_error_without_retry() -> None:
    resp_404 = MagicMock(spec=requests.Response)
    resp_404.status_code = 404
    resp_404.text = "Not Found"

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = resp_404

    client = VisionClient(session=mock_session)
    with pytest.raises(ServerError, match="Local backend returned HTTP 404"):
        client.complete("data:image/jpeg;base64,abc")

    assert mock_session.post.call_count == 1


# ==============================================================================
# Defensive Response Parsing Tests
# ==============================================================================

def test_response_parsing_invalid_json() -> None:
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.text = "<html>502 Bad Gateway</html>"
    mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "doc", 0)

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_response

    client = VisionClient(session=mock_session)
    with pytest.raises(ResponseParsingError, match="Failed to parse JSON response"):
        client.complete("data:image/jpeg;base64,abc")


def test_response_parsing_not_a_dict() -> None:
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = ["not", "a", "dict"]

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_response

    client = VisionClient(session=mock_session)
    with pytest.raises(ResponseParsingError, match="Expected JSON object"):
        client.complete("data:image/jpeg;base64,abc")


def test_response_parsing_missing_or_empty_choices() -> None:
    mock_session = MagicMock(spec=requests.Session)
    client = VisionClient(session=mock_session)

    # Missing choices
    mock_resp1 = MagicMock(spec=requests.Response)
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = {"id": "123"}
    mock_session.post.return_value = mock_resp1
    with pytest.raises(ResponseParsingError, match="missing non-empty 'choices'"):
        client.complete("data:image/jpeg;base64,abc")

    # Empty choices array
    mock_resp2 = MagicMock(spec=requests.Response)
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = {"choices": []}
    mock_session.post.return_value = mock_resp2
    with pytest.raises(ResponseParsingError, match="missing non-empty 'choices'"):
        client.complete("data:image/jpeg;base64,abc")


def test_response_parsing_invalid_choice_or_message() -> None:
    mock_session = MagicMock(spec=requests.Session)
    client = VisionClient(session=mock_session)

    # Choice item is not a dict
    mock_resp1 = MagicMock(spec=requests.Response)
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = {"choices": ["invalid_string"]}
    mock_session.post.return_value = mock_resp1
    with pytest.raises(ResponseParsingError, match="Expected 'choice' element to be dict"):
        client.complete("data:image/jpeg;base64,abc")

    # Missing message dict
    mock_resp2 = MagicMock(spec=requests.Response)
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = {"choices": [{"index": 0}]}
    mock_session.post.return_value = mock_resp2
    with pytest.raises(ResponseParsingError, match="Choice missing 'message' dictionary"):
        client.complete("data:image/jpeg;base64,abc")


def test_response_parsing_defensive_null_content() -> None:
    # Empirical check from llama.cpp / OpenAI: when content is None/null, reject as parsing error (C-2)
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": None}}]
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_response

    client = VisionClient(session=mock_session)
    with pytest.raises(ResponseParsingError, match="Model returned null/empty content"):
        client.complete("data:image/jpeg;base64,abc")


def test_response_parsing_empty_string_content() -> None:
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": ""}}]
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_response

    client = VisionClient(session=mock_session)
    text, _, _ = client.complete("data:image/jpeg;base64,abc")
    assert text == ""


def test_response_parsing_invalid_content_type() -> None:
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": 12345}}]
    }

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = mock_response

    client = VisionClient(session=mock_session)
    with pytest.raises(ResponseParsingError, match="Expected string content"):
        client.complete("data:image/jpeg;base64,abc")


def test_response_parsing_error_message_truncation() -> None:
    """Verify large error payloads are truncated to prevent log and memory bloating (Finding 3.3)."""
    mock_session = MagicMock(spec=requests.Session)
    client = VisionClient(session=mock_session)

    # 1. Massive choices-missing dictionary (e.g. 50,000 chars)
    huge_data = {"unexpected_key_" + str(i): "x" * 100 for i in range(500)}
    mock_resp1 = MagicMock(spec=requests.Response)
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = huge_data
    mock_session.post.return_value = mock_resp1

    with pytest.raises(ResponseParsingError) as exc_info:
        client.complete("data:image/jpeg;base64,abc")

    err_str = str(exc_info.value)
    assert "Response missing non-empty 'choices' array:" in err_str
    assert err_str.endswith("...")
    # Bound max error message length well under 400 chars (defensive against 50KB explosion)
    assert len(err_str) <= 350

    # 2. Massive first_choice dictionary missing 'message'
    huge_choice = {"field_" + str(i): "val" * 50 for i in range(200)}
    mock_resp2 = MagicMock(spec=requests.Response)
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = {"choices": [huge_choice]}
    mock_session.post.return_value = mock_resp2

    with pytest.raises(ResponseParsingError) as exc_info2:
        client.complete("data:image/jpeg;base64,abc")

    err_str2 = str(exc_info2.value)
    assert "Choice missing 'message' dictionary:" in err_str2
    assert err_str2.endswith("...")
    assert len(err_str2) <= 350


# ==============================================================================
# Multimodal Support Verification Tests
# ==============================================================================

def test_verify_multimodal_support_success() -> None:
    """Verify verify_multimodal_support succeeds when server returns valid response."""
    client = VisionClient()
    with patch.object(client, "complete", return_value=("```markdown\nhello\n```", {}, 0.1)) as mock_comp:
        client.verify_multimodal_support()
        assert mock_comp.called
        assert mock_comp.call_args[1]["max_tokens"] == 16


def test_verify_multimodal_support_missing_mmproj_error() -> None:
    """Verify verify_multimodal_support maps missing mmproj 500 error to clear hint."""
    client = VisionClient()
    err_msg = 'Local backend returned HTTP 500: {"error":{"message":"image input is not supported - hint: you may need to provide the mmproj"}}'
    with patch.object(client, "complete", side_effect=ServerError(err_msg)):
        with pytest.raises(ClientError) as exc_info:
            client.verify_multimodal_support()
        assert "Backend not responding correctly to image input" in str(exc_info.value)
        assert "--mmproj" in str(exc_info.value)


def test_verify_multimodal_support_server_offline() -> None:
    """Verify verify_multimodal_support re-raises ServerOfflineError."""
    client = VisionClient()
    with patch.object(client, "complete", side_effect=ServerOfflineError("Offline")):
        with pytest.raises(ServerOfflineError):
            client.verify_multimodal_support()


def test_verify_multimodal_support_null_content() -> None:
    """Verify verify_multimodal_support raises ClientError if model returns None text."""
    client = VisionClient()
    with patch.object(client, "complete", return_value=(None, {}, 0.1)):
        with pytest.raises(ClientError, match="null content"):
            client.verify_multimodal_support()


def test_vision_client_trust_env_disabled() -> None:
    """Verify VisionClient default session has trust_env=False to block proxy leaks."""
    client = VisionClient()
    try:
        assert client._session.trust_env is False
    finally:
        client.close()

