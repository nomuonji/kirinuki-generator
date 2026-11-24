"""AMD Token Lab OpenAI-compatible Chat Completions client.

Credentials are read from AMD_TOKENLAB_API_KEY only and are never logged.
"""
from __future__ import annotations

import os
import re
import time
from types import SimpleNamespace
from typing import Any, Mapping

import requests

DEFAULT_MODEL = "DeepSeek-V4.1-Flash-1017"
DEFAULT_BASE_URL = "https://api.tokenlab.amd.com/v1/chat/completions"
_TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


class TokenLabAPIError(RuntimeError):
    """A Token Lab request failed without a usable completion."""


def _messages(contents: Any) -> list[dict[str, str]]:
    if isinstance(contents, str):
        text = contents.strip()
        if not text:
            raise ValueError("Token Lab request requires non-empty prompt content")
        return [{"role": "user", "content": text}]
    if not isinstance(contents, (list, tuple)):
        text = str(contents).strip()
        if not text:
            raise ValueError("Token Lab request requires non-empty prompt content")
        return [{"role": "user", "content": text}]
    parts = [str(part) for part in contents if part is not None and str(part).strip()]
    if not parts:
        raise ValueError("Token Lab request requires non-empty prompt content")
    if len(parts) == 1:
        return [{"role": "user", "content": parts[0]}]
    return [
        {"role": "system", "content": parts[0]},
        {"role": "user", "content": "\n".join(parts[1:])},
    ]


def _config_value(config: Any, key: str, default: Any = None) -> Any:
    if isinstance(config, Mapping):
        return config.get(key, default)
    return getattr(config, key, default)


def _response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise TokenLabAPIError("Token Lab returned a non-object response")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise TokenLabAPIError("Token Lab response has no completion choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise TokenLabAPIError("Token Lab response has no assistant message")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        chunks = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        ]
        joined = "".join(chunks).strip()
        if joined:
            return joined
    raise TokenLabAPIError("Token Lab returned empty assistant content")


def generate_tokenlab_completion(
    contents: Any,
    *,
    generation_config: Any = None,
    request_options: Mapping[str, Any] | None = None,
    attempts: int = 2,
    sleep=time.sleep,
    notify=print,
    http_post=None,
):
    key = os.environ.get("AMD_TOKENLAB_API_KEY", "").strip()
    if not key:
        raise RuntimeError("AMD_TOKENLAB_API_KEY is not set; add this secret to use AMD Token Lab")

    model = os.environ.get("AMD_TOKENLAB_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise ValueError("Invalid AMD Token Lab model identifier")
    base_url = os.environ.get("AMD_TOKENLAB_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    if not base_url.startswith("https://"):
        raise ValueError("AMD_TOKENLAB_BASE_URL must use HTTPS")

    timeout_cap = 180
    try:
        timeout_cap = max(30, int(os.environ.get("OPENCODE_GO_MAX_TIMEOUT_SECONDS", "180")))
    except (TypeError, ValueError):
        pass
    timeout = timeout_cap
    configured_attempts = attempts
    if request_options:
        try:
            timeout = max(1, min(timeout_cap, int(request_options.get("timeout", timeout_cap))))
            if request_options.get("attempts") is not None:
                configured_attempts = int(request_options["attempts"])
        except (TypeError, ValueError):
            raise ValueError("Invalid request options for AMD Token Lab")

    max_attempts = max(1, min(3, configured_attempts))
    payload: dict[str, Any] = {
        "model": model,
        "messages": _messages(contents),
        "max_tokens": max(256, min(32768, int(os.environ.get("AMD_TOKENLAB_MAX_TOKENS", "4096")))),
    }
    temperature = _config_value(generation_config, "temperature")
    if temperature is not None:
        payload["temperature"] = float(temperature)

    post = http_post or requests.post
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "kirinuki-generator/1.0",
    }

    for attempt in range(max_attempts):
        try:
            response = post(base_url, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            if attempt + 1 == max_attempts:
                raise TokenLabAPIError(
                    f"Token Lab network failure after {max_attempts} attempts ({type(exc).__name__})"
                ) from exc
            delay = min(2 ** (attempt + 1), 8)
            notify(f"Token Lab transient network error; retrying in {delay}s ({attempt + 2}/{max_attempts})")
            sleep(delay)
            continue

        status = int(getattr(response, "status_code", 0) or 0)
        if status in _TRANSIENT_STATUSES:
            if attempt + 1 == max_attempts:
                raise TokenLabAPIError(f"Token Lab returned transient HTTP {status} after {max_attempts} attempts")
            retry_after = None
            try:
                retry_after = float((getattr(response, "headers", {}) or {}).get("Retry-After"))
            except (TypeError, ValueError):
                pass
            delay = max(1, min(15, retry_after if retry_after is not None else 2 ** (attempt + 1)))
            notify(f"Token Lab temporary HTTP {status}; retrying in {delay}s ({attempt + 2}/{max_attempts})")
            sleep(delay)
            continue
        if status < 200 or status >= 300:
            raise TokenLabAPIError(f"Token Lab API returned HTTP {status}")

        try:
            data = response.json()
        except (ValueError, AttributeError) as exc:
            raise TokenLabAPIError("Token Lab returned invalid JSON") from exc
        text = _response_text(data)
        return SimpleNamespace(text=text, raw=data, model=model)

    raise TokenLabAPIError("Token Lab request failed after retries")
