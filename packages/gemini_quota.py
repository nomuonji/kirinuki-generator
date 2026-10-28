"""Bounded retry for transient Gemini rate limits and server-capacity failures."""
from __future__ import annotations
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
