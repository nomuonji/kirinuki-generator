from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class OperationsConfig:
    posts_per_day: float = 2.0
    target_stock_days: float = 7.0
    reorder_stock_days: float = 3.0
    max_videos_per_run: int = 2
    clips_per_source_cap: int = 8
    max_search_videos: int = 30
    min_source_age_minutes: float = 30.0
    max_source_age_days: float = 21.0
    fallback_max_source_age_days: float = 90.0
    min_selection_score: float = 0.35

    @property
    def target_stock_clips(self) -> int:
        return max(1, math.ceil(self.posts_per_day * self.target_stock_days))

    @property
    def reorder_stock_clips(self) -> int:
        return max(1, math.ceil(self.posts_per_day * self.reorder_stock_days))

    @classmethod
    def from_env(cls) -> "OperationsConfig":
        return cls(
            posts_per_day=float(os.environ.get("CLIP_POSTS_PER_DAY", "2")),
            target_stock_days=float(os.environ.get("CLIP_STOCK_TARGET_DAYS", "7")),
            reorder_stock_days=float(os.environ.get("CLIP_STOCK_REORDER_DAYS", "3")),
            max_videos_per_run=max(1, int(os.environ.get("MAX_VIDEOS_PER_RUN", "2"))),
            clips_per_source_cap=max(1, int(os.environ.get("CLIPS_PER_SOURCE_CAP", "8"))),
            max_search_videos=max(5, int(os.environ.get("MAX_SEARCH_VIDEOS", "30"))),
            min_source_age_minutes=max(
                0.0, float(os.environ.get("MIN_SOURCE_AGE_MINUTES", "30"))
            ),
            max_source_age_days=max(
                1.0, float(os.environ.get("MAX_SOURCE_AGE_DAYS", "21"))
            ),
            fallback_max_source_age_days=max(
                1.0, float(os.environ.get("FALLBACK_MAX_SOURCE_AGE_DAYS", "90"))
            ),
            min_selection_score=min(
                1.0, max(0.0, float(os.environ.get("MIN_SELECTION_SCORE", "0.35")))
            ),
        )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def estimate_effective_stock(
    entries: Iterable[dict],
    posts_per_day: float,
    now: datetime | None = None,
    max_history_days: float = 90.0,
) -> float:
    """
    Estimate ready-to-post inventory without requiring a posting API.

    Completed source videos add their uploaded clip count to stock. Between production
    events, stock is consumed FIFO at the configured expected posting rate. This makes
    the generator replenish approximately when the publishing queue would run low,
    instead of counting every historical Drive upload forever.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    cutoff_seconds = max_history_days * 86400
    events: list[tuple[datetime, int]] = []
    for entry in entries:
        if entry.get("status") != "completed":
            continue
        try:
            count = int(entry.get("uploadedClips") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        when = parse_timestamp(
            entry.get("completedAt") or entry.get("processedAt")
        )
        if when is None or when > now:
            continue
        if (now - when).total_seconds() > cutoff_seconds:
            continue
        events.append((when, count))

    if not events:
        return 0.0

    events.sort(key=lambda item: item[0])
    rate_per_second = max(0.0, posts_per_day) / 86400.0
    stock = 0.0
    cursor = events[0][0]

    for when, count in events:
        if when > cursor:
            stock = max(0.0, stock - (when - cursor).total_seconds() * rate_per_second)
        stock += count
        cursor = when

    if now > cursor:
        stock = max(0.0, stock - (now - cursor).total_seconds() * rate_per_second)

    return stock


def _percentile_ranks(values: list[float]) -> list[float]:
    if not values:
        return []
    if len(values) == 1:
        return [0.5]

    order = sorted(range(len(values)), key=lambda idx: values[idx])
    ranks = [0.0] * len(values)

    pos = 0
    while pos < len(order):
        start = pos
        value = values[order[pos]]
        while pos + 1 < len(order) and values[order[pos + 1]] == value:
            pos += 1
        end = pos
        average_rank = (start + end) / 2.0
        percentile = average_rank / (len(values) - 1)
        for index in order[start : end + 1]:
            ranks[index] = percentile
        pos += 1

    return ranks


def _duration_fit(duration_seconds: float) -> float:
    minutes = duration_seconds / 60.0
    if minutes < 6:
        return 0.0
    if minutes < 10:
        return 0.75
    if minutes <= 45:
        return 1.0
    if minutes <= 90:
        return 0.92
    if minutes <= 150:
        return 0.78
    return 0.62


def rank_source_candidates(
    candidates: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """
    Rank eligible source videos for clipping.

    Inputs should contain:
      video, videoId, title, publishedAt, durationSeconds, views, likes, comments.

    The score intentionally favors current audience response over simple recency:
      45% view velocity percentile
      20% engagement percentile
      25% freshness
      10% duration fit
    """
    if not candidates:
        return []

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    enriched: list[dict] = []
    velocity_values: list[float] = []
    engagement_values: list[float] = []

    for candidate in candidates:
        published = parse_timestamp(candidate.get("publishedAt")) or now
        age_hours = max(0.25, (now - published).total_seconds() / 3600.0)
        views = max(0, int(candidate.get("views") or 0))
        likes = max(0, int(candidate.get("likes") or 0))
        comments = max(0, int(candidate.get("comments") or 0))

        views_per_hour = views / age_hours
        engagement_rate = (likes + 2.0 * comments) / max(views, 1)

        item = dict(candidate)
        item["ageHours"] = age_hours
        item["viewsPerHour"] = views_per_hour
        item["engagementRate"] = engagement_rate
        enriched.append(item)
        velocity_values.append(math.log1p(views_per_hour))
        engagement_values.append(math.log1p(engagement_rate * 10000.0))

    velocity_ranks = _percentile_ranks(velocity_values)
    engagement_ranks = _percentile_ranks(engagement_values)

    for idx, item in enumerate(enriched):
        # 5-day exponential decay keeps strong recent videos competitive without
        # blindly selecting the newest upload.
        freshness = math.exp(-item["ageHours"] / (24.0 * 5.0))
        duration_score = _duration_fit(float(item.get("durationSeconds") or 0.0))
        score = (
            0.45 * velocity_ranks[idx]
            + 0.20 * engagement_ranks[idx]
            + 0.25 * freshness
            + 0.10 * duration_score
        )
        item["velocityPercentile"] = velocity_ranks[idx]
        item["engagementPercentile"] = engagement_ranks[idx]
        item["freshnessScore"] = freshness
        item["durationFitScore"] = duration_score
        item["selectionScore"] = score

    enriched.sort(
        key=lambda item: (
            item["selectionScore"],
            item["viewsPerHour"],
            item["views"],
        ),
        reverse=True,
    )
    return enriched


def clips_needed_for_source(
    effective_stock: float,
    target_stock: int,
    per_source_cap: int,
) -> int:
    deficit = max(0, math.ceil(target_stock - effective_stock))
    if deficit <= 0:
        return 0
    return max(1, min(per_source_cap, deficit))
