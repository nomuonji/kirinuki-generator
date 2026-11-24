"""Google Gemini generateContent adapter for existing JSON-based kirinuki tasks.

No Gemini SDK dependency is required; authentication is exclusively by API key
from the environment. Model output still passes downstream editorial QA gates.
"""
from __future__ import annotations

import os
import re
import time
from types import SimpleNamespace
from typing import Any, Mapping

import requests

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
_TRANSIENT = {408, 429, 500, 502, 503, 504}


class GeminiAPIError(RuntimeError):
    """A Gemini request failed without a safe usable response."""


def _config_value(config: Any, key: str, default: Any = None) -> Any:
    if isinstance(config, Mapping):
        return config.get(key, default)
    return getattr(config, key, default)


def _make_payload(contents: Any, generation_config: Any) -> dict[str, Any]:
    if isinstance(contents, (tuple, list)):
        parts = [str(c) for c in contents if c is not None and str(c).strip()]
        if not parts:
            raise ValueError("Gemini request requires non-empty content")
        instructions = parts[0] if len(parts) > 1 else None
        user_text = "\n".join(parts[1:] if len(parts) > 1 else parts)
    else:
        instructions = None
        user_text = str(contents)
    if not user_text.strip():
        raise ValueError("Gemini request requires non-empty user text")
    cfg: dict[str, Any] = {
        "responseMimeType": "application/json",
        "maxOutputTokens": max(256, min(65536, int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "8192")))),
    }
    temperature = _config_value(generation_config, "temperature")
    if temperature is not None:
        cfg["temperature"] = float(temperature)
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": cfg,
    }
    if instructions:
        payload["systemInstruction"] = {"parts": [{"text": instructions}]}
    return payload


def generate_gemini_completion(
    contents: Any,
    *, generation_config: Any = None, request_options: Mapping[str, Any] | None = None,
    attempts: int = 2, sleep=time.sleep, notify=print, http_post=None,
):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set; set this secret to use Gemini")
    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
        raise ValueError("Invalid GEMINI_MODEL identifier")
    timeout_cap = max(30, int(os.environ.get("OPENCODE_GO_MAX_TIMEOUT_SECONDS", "180")))
    timeout = timeout_cap
    configured_attempts = attempts
    if request_options:
        try:
            timeout = max(1, min(timeout_cap, int(request_options.get("timeout", timeout_cap))))
            if request_options.get("attempts") is not None:
                configured_attempts = int(request_options["attempts"])
        except (ValueError, TypeError):
            raise ValueError("Invalid request options for Gemini")
    max_attempts = max(1, min(3, configured_attempts))
    post = http_post or requests.post
    payload = _make_payload(contents, generation_config)
    url = f"{_ENDPOINT}/{model}:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    for attempt in range(max_attempts):
        try:
            response = post(url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            if attempt + 1 == max_attempts:
                raise GeminiAPIError(f"Gemini network failure ({type(exc).__name__})") from exc
            sleep(min(2 ** (attempt + 1), 8))
            continue
        status = int(getattr(response, "status_code", 0) or 0)
        if status in _TRANSIENT and attempt + 1 < max_attempts:
            notify(f"Gemini temporary HTTP {status}; retry {attempt + 2}/{max_attempts}")
            sleep(min(2 ** (attempt + 1), 8))
            continue
        if status < 200 or status >= 300:
            raise GeminiAPIError(f"Gemini API returned HTTP {status}; model={model}")
        try:
            data = response.json()
        except (ValueError, AttributeError) as exc:
            raise GeminiAPIError("Gemini API returned invalid JSON") from exc
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(candidates, list) or not candidates:
            raise GeminiAPIError("Gemini returned no candidates (possibly safety-blocked)")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise GeminiAPIError("Gemini returned a malformed candidate")
        content = candidate.get("content") or {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        answer = "".join(str(p["text"]) for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)).strip()
        if not answer:
            raise GeminiAPIError(f"Gemini returned empty text (finishReason={candidate.get('finishReason')})")
        return SimpleNamespace(text=answer, raw=data, model=model)
    raise GeminiAPIError("Gemini request exhausted retries")
