"""Bounded retry for transient Gemini per-minute 429s only."""
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
    """Return cooldown seconds only for a transient per-minute 429.

    Daily/project quota exhaustion must fail immediately instead of wasting
    runner time on retries that cannot succeed before the quota resets.
    """
    message = _exception_text(exc)
    lowered = message.lower()
    if "429" not in message and "resourceexhausted" not in type(exc).__name__.lower():
        return None
    daily_markers = (
        "perday",
        "per_day",
        "per day",
        "daily quota",
        "daily limit",
        "requestsperday",
        "generate_content_free_tier_requests",
    )
    if any(marker in lowered for marker in daily_markers):
        return None
    matched = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", message, flags=re.I | re.S)
    if not matched:
        matched = re.search(r"retry in\s*(\d+(?:\.\d+)?)\s*s", message, flags=re.I)
    seconds = float(matched.group(1)) if matched else 60.0
    return max(10.0, min(120.0, seconds + 3.0))


def with_quota_retry(fn, *, attempts=4, sleep=time.sleep, notify=print):
    """Retry transient per-minute quota errors without catching other failures.

    Persistent quota and editorial QA errors propagate; quality gates remain
    fail-closed.
    """
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as exc:
            delay = quota_delay(exc)
            if delay is None or i >= attempts - 1:
                raise
            notify(f"Gemini per-minute quota reached; pause {delay:.0f}s (retry {i+2}/{attempts})")
            sleep(delay)
    raise RuntimeError("Unexpected retry state")
