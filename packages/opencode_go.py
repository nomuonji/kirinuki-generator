"""OpenCode Go client using its OpenAI-compatible Chat Completions API.

The default model is DeepSeek V4.1 Flash. API keys are read from environment
variables only and are never written to logs or request diagnostics.
"""
from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import Any, Mapping

import requests

DEFAULT_MODEL = "deepseek-v4.1-flash"
DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1/chat/completions"
_TRANSIENT_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenCodeGoAPIError(RuntimeError):
    """Raised when OpenCode Go returns an invalid response or API error."""


def _model_id(model_name: str | None) -> str:
    model = str(model_name or "").strip()
    # Smoothly migrate older workflow variables without ever calling Gemini.
    if not model or model.lower().startswith("gemini-"):
        model = os.environ.get("OPENCODE_GO_MODEL", DEFAULT_MODEL).strip()
    return model or DEFAULT_MODEL


def _messages(contents: Any) -> list[dict[str, str]]:
    if isinstance(contents, str):
        return [{"role": "user", "content": contents}]
    if not isinstance(contents, (list, tuple)):
        return [{"role": "user", "content": str(contents)}]
    parts = [str(part) for part in contents if part is not None and str(part).strip()]
    if not parts:
        raise ValueError("OpenCode Go request requires non-empty prompt content")
    if len(parts) == 1:
        return [{"role": "user", "content": parts[0]}]
    # Existing pipeline calls provide instructions first, followed by transcript/data.
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
        raise OpenCodeGoAPIError("OpenCode Go returned a non-object response")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise OpenCodeGoAPIError("OpenCode Go response has no completion choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise OpenCodeGoAPIError("OpenCode Go response has no assistant message")
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
    raise OpenCodeGoAPIError("OpenCode Go returned empty assistant content")


def generate_chat_completion(
    model_name: str | None,
    contents: Any,
    *,
    generation_config: Any = None,
    request_options: Mapping[str, Any] | None = None,
    attempts: int = 3,
    sleep=time.sleep,
    notify=print,
    http_post=None,
):
    """Generate text through OpenCode Go with bounded transient-error retries.

    Gemini-only response schemas are intentionally not forwarded. Callers already
    instruct the model to return JSON, which is parsed and independently validated
    by the existing pipeline before a clip can proceed.
    """
    api_key = (
        os.environ.get("OPENCODE_GO_API_KEY")
        or os.environ.get("OPENCODE_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise RuntimeError(
            "OPENCODE_GO_API_KEY is not set; add your OpenCode Go API key as a secret/env var"
        )

    base_url = os.environ.get("OPENCODE_GO_BASE_URL", DEFAULT_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_BASE_URL
    timeout = 600
    if request_options:
        try:
            timeout = max(1, int(request_options.get("timeout", timeout)))
        except (TypeError, ValueError):
            pass
    max_attempts = max(1, min(int(attempts), 5))
    post = http_post or requests.post

    payload: dict[str, Any] = {
        "model": _model_id(model_name),
        "messages": _messages(contents),
    }
    temperature = _config_value(generation_config, "temperature")
    if temperature is not None:
        payload["temperature"] = float(temperature)
    max_tokens = os.environ.get("OPENCODE_GO_MAX_TOKENS", "8192").strip()
    if max_tokens:
        try:
            payload["max_tokens"] = max(1, int(max_tokens))
        except ValueError:
            raise RuntimeError("OPENCODE_GO_MAX_TOKENS must be a positive integer")

    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            response = post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= max_attempts - 1:
                raise OpenCodeGoAPIError(
                    f"OpenCode Go request failed after {max_attempts} attempts ({type(exc).__name__})"
                ) from exc
            delay = min(2 ** (attempt + 1), 20)
            notify(f"OpenCode Go transient network error; retrying in {delay}s ({attempt + 2}/{max_attempts})")
            sleep(delay)
            continue

        status = int(getattr(response, "status_code", 0) or 0)
        if status in _TRANSIENT_STATUSES:
            body = str(getattr(response, "text", "") or "")[:300]
            last_error = OpenCodeGoAPIError(f"HTTP {status}: {body}")
            if attempt >= max_attempts - 1:
                raise last_error
            retry_after = None
            headers = getattr(response, "headers", {}) or {}
            try:
                retry_after = float(headers.get("Retry-After"))
            except (TypeError, ValueError):
                pass
            delay = max(1, min(30, retry_after if retry_after is not None else 2 ** (attempt + 1)))
            notify(f"OpenCode Go returned transient HTTP {status}; retrying in {delay:.0f}s ({attempt + 2}/{max_attempts})")
            sleep(delay)
            continue

        if status < 200 or status >= 300:
            body = str(getattr(response, "text", "") or "")[:300]
            raise OpenCodeGoAPIError(f"OpenCode Go API returned HTTP {status}: {body}")

        try:
            result = response.json()
        except (ValueError, AttributeError) as exc:
            raise OpenCodeGoAPIError("OpenCode Go returned invalid JSON") from exc
        text = _response_text(result)
        return SimpleNamespace(text=text, raw=result, model=payload["model"])

    raise OpenCodeGoAPIError(f"OpenCode Go request failed: {last_error}")
