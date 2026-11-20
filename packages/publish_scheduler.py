"""Deterministic YouTube reservation slots and publish deduplication."""
from __future__ import annotations
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
SLOTS = ((12, 0), (20, 0))


def utc_now():
    return datetime.now(timezone.utc)


def aware(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fingerprint(source_id: str, start: float, end: float, version="v1") -> str:
    canonical = f"{source_id}:{round(float(start), 2):.2f}:{round(float(end), 2):.2f}:{version}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def marker(key: str) -> str:
    return f"KIRINUKI-ID:{key}"


def reserve_slots(entries: list[dict], *, now=None, days=14, max_count=20,
                  source_id=None, one_source_per_day=True):
    """Schedule in JST and avoid occupied times; dates are returned in UTC ISO8601.

    entries: [{publishAt, sourceVideoId}], including YouTube's actual reservations
    and the durable ledger; avoid guessing that the ledger alone is current.
    """
    now = aware(now or utc_now()).astimezone(timezone.utc)
    existing_times = set()
    same_source_days = set()
    for entry in entries:
        stamp = entry.get("publishAt")
        if not stamp:
            continue
        try:
            when = aware(stamp).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        existing_times.add(when)
        if entry.get("sourceVideoId") == source_id and source_id:
            same_source_days.add(when.astimezone(JST).date())

    slots = []
    today = now.astimezone(JST).date()
    for offset in range(max(0, int(days))):
        day = today + timedelta(days=offset)
        if one_source_per_day and source_id and day in same_source_days:
            continue
        for hour, minute in SLOTS:
            local_time = datetime(day.year, day.month, day.day, hour, minute, tzinfo=JST)
            when = local_time.astimezone(timezone.utc)
            if when <= now + timedelta(minutes=45):
                continue
            if when in existing_times:
                continue
            slots.append(when.isoformat().replace("+00:00", "Z"))
            existing_times.add(when)
            if one_source_per_day and source_id:
                same_source_days.add(day)
                break
            if len(slots) >= max_count:
                return slots
        if len(slots) >= max_count:
            return slots
    return slots


def rolling_uploads(entries, *, now=None, hours=24):
    now = aware(now or utc_now()).astimezone(timezone.utc)
    begin = now - timedelta(hours=hours)
    n = 0
    for item in entries:
        when = item.get("uploadedAt")
        if not when:
            continue
        try:
            if begin <= aware(when).astimezone(timezone.utc) <= now:
                n += 1
        except (ValueError, TypeError):
            pass
    return n


def eligible_to_post(env) -> tuple[bool, str]:
    """All gates are explicit; none can be inferred from source MCN participation."""
    gates = ("KIRINUKI_DIRECT_MODE", "KIRINUKI_AUTOPUBLISH_ENABLED",
             "KIRINUKI_SOURCE_RIGHTS_APPROVED", "KIRINUKI_CHANNEL_AUTHORIZED")
    missing = [key for key in gates if str(env.get(key, "")).lower() != "true"]
    if missing:
        return False, "inactive: " + ", ".join(missing)
    secrets = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
               "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_DESTINATION_CHANNEL_ID")
    missing = [key for key in secrets if not str(env.get(key, "")).strip()]
    if missing:
        return False, "missing: " + ", ".join(missing)
    return True, "approved_configured"
