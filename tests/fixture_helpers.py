"""Shared test fixture helpers for loading real wire responses and payloads."""

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_real_glm_ocr_response(
    content: Optional[str] = None,
    cmpl_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Load the empirical wire GLM-OCR response captured from live llama-server.

    Allows overriding extracted markdown content and completion ID while preserving
    100% schema fidelity (usage tokens, timings breakdown, choices structure, model name).

    Args:
        content: Optional markdown text to substitute into choices[0].message.content.
        cmpl_id: Optional ID string to substitute into id.

    Returns:
        Dict[str, Any]: Deep-copied, wire-accurate response dictionary.
    """
    fixture_file = _FIXTURES_DIR / "real_glm_ocr_response.json"
    raw_dict: Dict[str, Any] = json.loads(fixture_file.read_text(encoding="utf-8"))
    res = copy.deepcopy(raw_dict)
    if content is not None:
        res["choices"][0]["message"]["content"] = content
    if cmpl_id is not None:
        res["id"] = cmpl_id
    return res


def load_real_glm_ocr_error_response(
    message: Optional[str] = None,
    code: int = 400,
) -> Dict[str, Any]:
    """Load the empirical wire GLM-OCR HTTP 400 error payload captured from live llama-server.

    Args:
        message: Optional custom error message string.
        code: Optional HTTP status code (defaults to 400).

    Returns:
        Dict[str, Any]: Deep-copied, wire-accurate error response dictionary.
    """
    fixture_file = _FIXTURES_DIR / "real_glm_ocr_error_response.json"
    raw_dict: Dict[str, Any] = json.loads(fixture_file.read_text(encoding="utf-8"))
    res = copy.deepcopy(raw_dict)
    if message is not None:
        res["error"]["message"] = message
    if code != 400:
        res["error"]["code"] = code
    return res
