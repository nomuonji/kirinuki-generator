# Kirinuki Operations Model

The production loop is stock-driven, not "process the newest upload every time."

## Posting stock policy

Defaults are configurable through environment variables:

- `CLIP_POSTS_PER_DAY=2`
- `CLIP_STOCK_TARGET_DAYS=7` → target 14 clips
- `CLIP_STOCK_REORDER_DAYS=3` → replenish below 6 clips
- `MAX_VIDEOS_PER_RUN=2`
- `CLIPS_PER_SOURCE_CAP=8`
- `MAX_SEARCH_VIDEOS=30`

Because this repository does not own the downstream social-posting API, it estimates **effective stock** from completed production events. Generated clips enter inventory at completion time; inventory is then consumed FIFO at `CLIP_POSTS_PER_DAY`. This avoids treating every historical Drive file as permanently available stock.

When a downstream posting system is connected later, its actual posted events can replace this estimated-consumption model without changing source selection.

## Replenishment logic

A scheduled run first executes a lightweight plan job.

1. Read `processed_videos.json` from the channel's Drive folder.
2. Estimate current effective clip stock.
3. Fetch up to 30 recent channel uploads.
4. Rank eligible sources.
5. Exit before installing ffmpeg/Remotion if no production is needed.
6. Otherwise run the full production job until target stock is reached or two source videos have been attempted.

The full production job is only started when:

- effective stock is below the reorder point; or
- stock is below target and a fresh high-quality source is available.

## Source-video ranking

Videos shorter than six minutes, live/upcoming videos, sources younger than 30 minutes, and sources older than 21 days are excluded by default. If posting stock is below the reorder point and that preferred window contains no eligible source, the search expands to 90 days and up to 100 uploads rather than leaving the queue empty.

Eligible recent videos are ranked against the **whole recent channel baseline**, including already processed videos. The score is:

- 45% view velocity percentile (views/hour)
- 20% engagement percentile
- 25% freshness
- 10% duration fit for clipping

This prevents a weak unprocessed leftover from looking strong merely because it is the only remaining candidate.

Selection metadata is written into `processed_videos.json`, including the score, source age data, view/like/comment counts at selection time, and uploaded clip count.

## Clip-production policy

The watcher calculates the current stock deficit and passes only the needed clip count to `run_all.py`.

A single source is capped at eight clips by default so one video does not dominate the queue. When Gemini proposes more clips than needed, `generate_clips.py` now keeps the highest-confidence proposals rather than the earliest proposals in transcript order.

The completion receipt records `uploadedClips`; the watcher copies this into `processed_videos.json` before deleting the per-video state file.

## Download policy

Production download order:

1. SaveTube CDN (validated on GitHub-hosted runners)
2. yt-dlp nightly fallback
3. optional legacy RapidAPI / Playwright fallback only when `ENABLE_LEGACY_DOWNLOAD_FALLBACKS=1`

The PO Token provider is started lazily only if SaveTube fails and the yt-dlp path is reached.

## Scheduling and concurrency

Primary, secondary, and tertiary workflows are checked four times per day, staggered by ten minutes. Healthy-stock runs stop in the lightweight plan job.

Each workflow has a concurrency lock with `cancel-in-progress: false`, preventing two runs for the same production lane from racing on Drive state or generating the same source concurrently.

## Retry behavior

Transient failures are retried up to three times with 6h / 24h / 72h backoff. Transcript failures are retryable because caption/API availability can recover. Permanent reasons such as a too-short source, a true geo restriction, or a known unavailable video are not retried.

The pipeline uses stage-level timeouts and a total wall-clock budget so a hung dependency cannot consume the six-hour GitHub Actions ceiling.

## Tuning

Typical adjustments:

- More aggressive posting: raise `CLIP_POSTS_PER_DAY`.
- Larger safety buffer: raise `CLIP_STOCK_TARGET_DAYS`.
- Replenish earlier: raise `CLIP_STOCK_REORDER_DAYS`.
- More source diversity: lower `CLIPS_PER_SOURCE_CAP`.
- More production per Actions run: raise `MAX_VIDEOS_PER_RUN` cautiously.
- Wider source pool: raise `MAX_SEARCH_VIDEOS` or `MAX_SOURCE_AGE_DAYS`.
