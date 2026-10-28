"""Bounded retry for transient Gemini rate limits and server-capacity failures."""
from __future__ import annotations
import os
import re
import time


def _exception_text(exc: Exception) -> str:
    """Include structured Google RPC details when identifying quota windows."""
    parts = [str(exc), repr(exc)]
    for attr in ("details", "_details", "errors", "message"):
        value = getattr(exc, attr, None)
        if value is None:
            continue
        try:
            value = value() if callable(value) else value
        except Exception:
            continue
        parts.append(repr(value))
    return " ".join(parts)


def quota_delay(exc: Exception) -> float | None:
    """Return a bounded cooldown only for transient 429s or server-capacity errors.

    Daily/project quota exhaustion and authentication, validation, or editorial
    failures must fail immediately instead of consuming more runner time.
    """
    message = _exception_text(exc)
    lowered = message.lower()
    type_name = type(exc).__name__.lower()
    is_rate_limited = "429" in message or "resourceexhausted" in type_name

    daily_markers = (
        "perday",
        "per_day",
        "per day",
        "daily quota",
        "daily limit",
        "requestsperday",
        "generate_content_free_tier_requests",
    )
    if is_rate_limited and any(marker in lowered for marker in daily_markers):
        return None

    transient_markers = (
        "serviceunavailable",
        "internalservererror",
        "badgateway",
        "gatewaytimeout",
        "temporarily unavailable",
        "high demand",
    )
    is_transient_server_error = (
        bool(re.search(r"\b(?:502|503|504)\b", message))
        or any(marker in lowered or marker in type_name for marker in transient_markers)
    )
    if not is_rate_limited and not is_transient_server_error:
        return None

    matched = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", message, flags=re.I | re.S)
    if not matched:
        matched = re.search(r"retry in\s*(\d+(?:\.\d+)?)\s*s", message, flags=re.I)
    if matched:
        seconds = float(matched.group(1)) + 3.0
    else:
        seconds = 15.0 if is_transient_server_error else 60.0
    return max(5.0, min(120.0 if is_rate_limited else 60.0, seconds))


def with_quota_retry(fn, *, attempts=4, sleep=time.sleep, notify=print):
    """Retry transient Gemini throttling/capacity errors, not daily quota failures."""
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as exc:
            delay = quota_delay(exc)
            if delay is None or i >= attempts - 1:
                raise
            notify(f"Gemini transient rate/capacity limit; pause {delay:.0f}s (retry {i+2}/{attempts})")
            sleep(delay)
    raise RuntimeError("Unexpected retry state")



def _is_fallback_worthy(exc: Exception) -> bool:
    """Permit a model switch only for throttling, quota, or temporary capacity failures."""
    message = _exception_text(exc).lower()
    type_name = type(exc).__name__.lower()
    return (
        "429" in message
        or "resourceexhausted" in type_name
        or bool(re.search(r"\\b(?:502|503|504)\\b", message))
        or any(marker in message or marker in type_name for marker in (
            "serviceunavailable", "internalservererror", "badgateway",
            "gatewaytimeout", "temporarily unavailable", "high demand",
        ))
    )


def generate_content_with_fallback(
    model_name: str,
    contents,
    *,
    generation_config=None,
    request_options=None,
    fallback_models: list[str] | None = None,
    model_factory=None,
    attempts: int = 2,
    sleep=time.sleep,
    notify=print,
):
    """Run Gemini generation with bounded model fallback on transient capacity/limit errors.

    Fallback never bypasses editorial QA and never handles authentication, malformed
    requests, or invalid application output. Daily-limit failures switch models
    immediately rather than retrying the exhausted model.
    """
    import google.generativeai as genai

    factory = model_factory or genai.GenerativeModel
    if fallback_models is None:
        fallback_models = [
            name.strip() for name in os.environ.get(
                "GEMINI_FALLBACK_MODELS",
                "gemini-2.5-flash-lite,gemini-3.5-flash-lite",
            ).split(",") if name.strip()
        ]
    names = []
    for name in [model_name, *fallback_models]:
        candidate = str(name or "").strip()
        if candidate and candidate not in names:
            names.append(candidate)
    if not names:
        raise ValueError("At least one Gemini model name is required")

    last_error = None
    for index, name in enumerate(names):
        model = factory(name)
        try:
            return with_quota_retry(
                lambda: model.generate_content(
                    contents,
                    generation_config=generation_config,
                    request_options=request_options,
                ),
                attempts=attempts,
                sleep=sleep,
                notify=notify,
            )
        except Exception as exc:
            last_error = exc
            if index == len(names) - 1 or not _is_fallback_worthy(exc):
                raise
            notify(
                f"Gemini model {name} unavailable or quota-limited; "
                f"falling back to {names[index + 1]} ({type(exc).__name__})."
            )
    raise last_error
