"""Bounded retry of Gemini 429 RPM limits; never downgrade editorial QA."""
from __future__ import annotations
import re
import time


def quota_delay(exc: Exception) -> float | None:
    """Return cooldown seconds only for a transient per-minute 429.

    Per-day/token budget failures must not enter a needless retry loop.
    """
    message = str(exc)
    if "429" not in message and "ResourceExhausted" not in type(exc).__name__:
        return None
    if any(x in message for x in ("PerDay", "per day", "daily quota", "daily limit")):
        return None
    matched = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", message, flags=re.I | re.S)
    if not matched:
        matched = re.search(r"retry in\s*(\d+(?:\.\d+)?)\s*s", message, flags=re.I)
    seconds = float(matched.group(1)) if matched else 60.0
    return max(10.0, min(120.0, seconds + 3.0))


def with_quota_retry(fn, *, attempts=4, sleep=time.sleep, notify=print):
    """Retry a transient quota rejection without catching unrelated failures.

    A source still fails closed on persistent quota/review errors. Do not
    silently omit the independent editorial pass to produce stock.
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
