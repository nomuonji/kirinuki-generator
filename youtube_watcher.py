import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from packages.operations import (
    OperationsConfig,
    clips_needed_for_source,
    estimate_drive_clip_stock,
    estimate_effective_stock,
    parse_timestamp,
    rank_source_candidates,
)
from packages.shared.gdrive import (
    delete_file,
    download_file_bytes,
    find_file,
    get_drive_service,
    list_clip_files,
    upload_json_data,
)

MIN_VIDEO_DURATION_SECONDS = 360
PROCESSED_LOG_NAME = "processed_videos.json"

MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_HOURS = (6, 24, 72)

# A missing transcript may be a temporary provider/caption failure, so it is no longer
# permanent on the first miss. These reasons genuinely do not improve by retrying.
PERMANENT_FAILURE_REASONS = {"duration_too_short", "geo_restricted", "video_unavailable"}
STALE_FAILURE_DAYS = 30


def _older_than(timestamp: str | None, days: int) -> bool:
    when = parse_timestamp(timestamp)
    return bool(when and datetime.now(timezone.utc) - when > timedelta(days=days))


def _is_retryable(entry: dict) -> bool:
    status = entry.get("status")
    if status not in {"failed", "in-progress"}:
        return False

    if entry.get("reason") in PERMANENT_FAILURE_REASONS:
        return False

    last_attempt = entry.get("processedAt")
    if _older_than(last_attempt, STALE_FAILURE_DAYS):
        return False

    attempts = int(entry.get("attempts") or 1)
    if attempts >= MAX_RETRY_ATTEMPTS:
        return False

    last = parse_timestamp(last_attempt)
    if last is None:
        return True

    backoff = RETRY_BACKOFF_HOURS[min(attempts, len(RETRY_BACKOFF_HOURS)) - 1]
    return datetime.now(timezone.utc) - last >= timedelta(hours=backoff)


class Deadline:
    def __init__(self, minutes: float, min_video_minutes: float):
        self._end = time.monotonic() + minutes * 60
        self._min_video_seconds = min_video_minutes * 60

    def remaining(self) -> float:
        return self._end - time.monotonic()

    def exhausted(self) -> bool:
        return self.remaining() <= 0

    def can_start_video(self) -> bool:
        return self.remaining() >= self._min_video_seconds

    def summary(self) -> str:
        return f"{max(0.0, self.remaining()) / 60:.1f} min remaining"


def run_command(command, description, timeout=None):
    print(f"--- {description} ---")
    print("Executing:", " ".join(map(str, command)))

    child_env = os.environ.copy()
    child_env["PYTHONUNBUFFERED"] = "1"

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        env=child_env,
    )

    timed_out = {"value": False}
    if timeout is not None:
        def _watch():
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out["value"] = True
                print(
                    f"\nTimeout: '{description}' exceeded {timeout / 60:.0f} min; terminating.",
                    file=sys.stderr,
                )
                try:
                    process.terminate()
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                except OSError:
                    pass

        threading.Thread(target=_watch, daemon=True).start()

    for line in iter(process.stdout.readline, ""):
        print(line, end="", flush=True)
    process.stdout.close()
    return_code = process.wait()

    if timed_out["value"]:
        print(f"\nERROR: '{description}' timed out.", file=sys.stderr)
        return False

    if return_code != 0:
        print(
            f"\nERROR during '{description}': Command returned non-zero exit status {return_code}.",
            file=sys.stderr,
        )
        return False

    print(f"\n--- Finished: {description} ---\n")
    return True


def get_uploads_playlist_id(api_key, channel_id):
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        response = youtube.channels().list(
            part="contentDetails",
            id=channel_id,
        ).execute()
        if not response.get("items"):
            print(f"Channel not found for ID: {channel_id}")
            return None
        return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except HttpError as exc:
        print(f"HTTP error retrieving channel info: {exc}", file=sys.stderr)
        return None


def fetch_recent_videos(api_key: str, playlist_id: str, limit: int) -> list[dict]:
    """Fetch recent uploads with statistics using low-cost playlist/videos API calls."""
    youtube = build("youtube", "v3", developerKey=api_key)
    collected: list[dict] = []
    page_token = None

    try:
        while len(collected) < limit:
            batch_size = min(50, limit - len(collected))
            playlist_response = youtube.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=batch_size,
                pageToken=page_token,
            ).execute()

            ids = [
                item["contentDetails"]["videoId"]
                for item in playlist_response.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            if ids:
                video_response = youtube.videos().list(
                    part="contentDetails,snippet,statistics,status",
                    id=",".join(ids),
                ).execute()
                collected.extend(video_response.get("items", []))

            page_token = playlist_response.get("nextPageToken")
            if not page_token or not ids:
                break
    except HttpError as exc:
        print(f"YouTube API error {exc.resp.status}: {exc.content}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"Error fetching source videos: {exc}", file=sys.stderr)
        return []

    collected.sort(
        key=lambda item: item.get("snippet", {}).get("publishedAt", ""),
        reverse=True,
    )
    return collected[:limit]


def parse_duration(duration_str):
    if not duration_str or not duration_str.startswith("PT"):
        return timedelta(0)

    duration_str = duration_str[2:]
    total_seconds = 0
    number_buffer = ""

    for char in duration_str:
        if char.isdigit():
            number_buffer += char
        elif char == "H" and number_buffer:
            total_seconds += int(number_buffer) * 3600
            number_buffer = ""
        elif char == "M" and number_buffer:
            total_seconds += int(number_buffer) * 60
            number_buffer = ""
        elif char == "S" and number_buffer:
            total_seconds += int(number_buffer)
            number_buffer = ""

    return timedelta(seconds=total_seconds)


def load_state_from_drive(service, folder_id: str, video_id: str) -> tuple[dict, str | None]:
    state_name = f"state_{video_id}.json"
    state_file = find_file(service, folder_id, state_name)
    if not state_file:
        return {}, None
    try:
        payload = download_file_bytes(service, state_file["id"])
        return json.loads(payload.decode("utf-8")), state_file["id"]
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Failed to parse remote state for {video_id}: {exc}", file=sys.stderr)
        return {}, state_file["id"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_processed_videos(service, folder_id: str) -> tuple[list[dict], str | None]:
    processed_file = find_file(service, folder_id, PROCESSED_LOG_NAME)
    if not processed_file:
        return [], None
    try:
        payload = download_file_bytes(service, processed_file["id"])
        data = json.loads(payload.decode("utf-8"))
        if isinstance(data, list):
            return data, processed_file["id"]
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Failed to parse processed video log: {exc}", file=sys.stderr)
    return [], processed_file["id"]


def save_processed_videos(service, folder_id: str, entries: list[dict], file_id: str | None) -> str:
    payload = json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")
    return upload_json_data(service, folder_id, PROCESSED_LOG_NAME, payload, file_id)


def record_processed_entry(
    service,
    folder_id: str,
    entries: list[dict],
    file_id: str | None,
    video_id: str,
    title: str,
    status: str,
    reason: str = "",
    metadata: dict | None = None,
) -> tuple[list[dict], str | None]:
    record = {
        "videoId": video_id,
        "title": title,
        "processedAt": _now_iso(),
        "status": status,
    }
    if reason:
        record["reason"] = reason
    if metadata:
        record.update({key: value for key, value in metadata.items() if value is not None})

    existing = next((entry for entry in entries if entry.get("videoId") == video_id), None)
    if status == "failed":
        record["attempts"] = int((existing or {}).get("attempts") or 0) + 1

    if existing:
        existing.update(record)
        if not reason:
            existing.pop("reason", None)
    else:
        entries.append(record)

    entries.sort(key=lambda entry: entry.get("processedAt", ""), reverse=True)
    file_id = save_processed_videos(service, folder_id, entries, file_id)
    return entries, file_id


def has_stock_ledger(entries: list[dict]) -> bool:
    for entry in entries:
        if entry.get("status") != "completed":
            continue
        try:
            if int(entry.get("uploadedClips") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def estimate_legacy_drive_stock(service, folder_id: str, posts_per_day: float) -> float:
    """
    Bootstrap pre-ledger inventory from MP4 creation times.

    Older Kirinuki runs uploaded clips to Drive but did not record uploadedClips in
    processed_videos.json. Count those files only until the new ledger has at least one
    stock-aware completion entry. Expected posting consumption is applied to their
    creation timestamps, so ancient archive files do not become fake current stock.
    """
    query = (
        f"'{folder_id}' in parents and mimeType = 'video/mp4' "
        "and trashed = false"
    )
    events: list[dict] = []
    page_token = None
    try:
        while True:
            response = service.files().list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, createdTime)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()
            for file_info in response.get("files", []):
                created = file_info.get("createdTime")
                if created:
                    events.append(
                        {
                            "status": "completed",
                            "processedAt": created,
                            "uploadedClips": 1,
                        }
                    )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        print(f"Warning: could not bootstrap Drive stock: {exc}", file=sys.stderr)
        return 0.0

    stock = estimate_effective_stock(events, posts_per_day=posts_per_day)
    print(
        f"Legacy Drive stock bootstrap: {len(events)} MP4 file(s), "
        f"{stock:.1f} effective clip(s) after expected consumption."
    )
    return stock


def prepare_stock_entries(
    processed_entries: list[dict],
    drive_service,
    folder_id: str,
    config: OperationsConfig,
    persist_bootstrap: bool,
    processed_file_id: str | None,
) -> tuple[list[dict], str | None, str]:
    if has_stock_ledger(processed_entries):
        return processed_entries, processed_file_id, "processed_ledger"

    bootstrap_stock = estimate_legacy_drive_stock(
        drive_service,
        folder_id,
        posts_per_day=config.posts_per_day,
    )
    bootstrap_count = max(0, math.floor(bootstrap_stock))
    if bootstrap_count <= 0:
        return processed_entries, processed_file_id, "empty"

    synthetic = {
        "videoId": "__legacy_stock_bootstrap__",
        "title": "Legacy Drive stock bootstrap",
        "processedAt": _now_iso(),
        "completedAt": _now_iso(),
        "status": "completed",
        "uploadedClips": bootstrap_count,
        "stockBootstrap": True,
    }

    if persist_bootstrap:
        existing = next(
            (
                entry for entry in processed_entries
                if entry.get("videoId") == "__legacy_stock_bootstrap__"
            ),
            None,
        )
        if existing:
            existing.update(synthetic)
        else:
            processed_entries.append(synthetic)
        processed_entries.sort(
            key=lambda entry: entry.get("processedAt", ""),
            reverse=True,
        )
        processed_file_id = save_processed_videos(
            drive_service,
            folder_id,
            processed_entries,
            processed_file_id,
        )
        print(f"Migrated {bootstrap_count} effective legacy clip(s) into stock ledger.")
        return processed_entries, processed_file_id, "drive_bootstrap_persisted"

    planning_entries = list(processed_entries) + [synthetic]
    return planning_entries, processed_file_id, "drive_bootstrap_preview"


def build_ranked_candidates(
    videos: list[dict],
    processed_ids: set[str],
    config: OperationsConfig,
    max_source_age_days: float | None = None,
    diagnostics: dict | None = None,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    candidates: list[dict] = []
    source_age_limit = max_source_age_days or config.max_source_age_days
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update({
        "fetched": len(videos),
        "missingId": 0,
        "tooShort": 0,
        "liveOrUpcoming": 0,
        "invalidPublishedAt": 0,
        "tooYoung": 0,
        "tooOld": 0,
        "eligibleBaseline": 0,
        "alreadyProcessed": 0,
        "unprocessedRanked": 0,
    })

    for video in videos:
        video_id = video.get("id")
        if not video_id:
            diag["missingId"] += 1
            continue

        snippet = video.get("snippet") or {}
        statistics = video.get("statistics") or {}
        duration_seconds = parse_duration(
            (video.get("contentDetails") or {}).get("duration", "")
        ).total_seconds()
        if duration_seconds < MIN_VIDEO_DURATION_SECONDS:
            diag["tooShort"] += 1
            continue

        if snippet.get("liveBroadcastContent") in {"live", "upcoming"}:
            diag["liveOrUpcoming"] += 1
            continue

        published_at = snippet.get("publishedAt")
        published = parse_timestamp(published_at)
        if published is None:
            diag["invalidPublishedAt"] += 1
            continue
        age = now - published
        if age.total_seconds() < config.min_source_age_minutes * 60:
            diag["tooYoung"] += 1
            continue
        if age > timedelta(days=source_age_limit):
            diag["tooOld"] += 1
            continue

        diag["eligibleBaseline"] += 1
        candidates.append(
            {
                "video": video,
                "videoId": video_id,
                "title": snippet.get("title") or video_id,
                "publishedAt": published_at,
                "durationSeconds": duration_seconds,
                "views": int(statistics.get("viewCount") or 0),
                "likes": int(statistics.get("likeCount") or 0),
                "comments": int(statistics.get("commentCount") or 0),
            }
        )

    # Rank against the whole recent eligible channel baseline first. If we ranked only
    # unprocessed videos, a single weak leftover would automatically look average/good.
    ranked = rank_source_candidates(candidates, now=now)
    diag["alreadyProcessed"] = sum(
        1 for item in ranked if item["videoId"] in processed_ids
    )
    result = [item for item in ranked if item["videoId"] not in processed_ids]
    diag["unprocessedRanked"] = len(result)
    return result


def selection_metadata(candidate: dict, uploaded_clips: int | None = None) -> dict:
    metadata = {
        "sourcePublishedAt": candidate.get("publishedAt"),
        "sourceDurationSeconds": round(float(candidate.get("durationSeconds") or 0.0), 3),
        "sourceViewsAtSelection": int(candidate.get("views") or 0),
        "sourceLikesAtSelection": int(candidate.get("likes") or 0),
        "sourceCommentsAtSelection": int(candidate.get("comments") or 0),
        "viewsPerHourAtSelection": round(float(candidate.get("viewsPerHour") or 0.0), 3),
        "selectionScore": round(float(candidate.get("selectionScore") or 0.0), 5),
    }
    if uploaded_clips is not None:
        metadata["uploadedClips"] = max(0, int(uploaded_clips))
        metadata["completedAt"] = _now_iso()
    return metadata


def make_plan(
    effective_stock: float,
    ranked_candidates: list[dict],
    config: OperationsConfig,
) -> dict:
    target = config.target_stock_clips
    reorder = config.reorder_stock_clips
    deficit = max(0, math.ceil(target - effective_stock))

    strong_candidates = [
        item for item in ranked_candidates
        if item.get("selectionScore", 0.0) >= config.min_selection_score
    ]
    if effective_stock < reorder and not strong_candidates and ranked_candidates:
        # Empty/critical stock is worse than taking the best available source.
        strong_candidates = ranked_candidates[:1]

    top = strong_candidates[0] if strong_candidates else None
    fresh_refill = bool(
        top
        and effective_stock < target
        and float(top.get("ageHours") or 999999) <= 24.0
        and float(top.get("selectionScore") or 0.0) >= 0.68
    )
    hot_capture = bool(
        top
        and effective_stock <= target + 2
        and float(top.get("ageHours") or 999999) <= 18.0
        and float(top.get("selectionScore") or 0.0) >= 0.82
    )
    needs_replenishment = effective_stock <= reorder
    should_process = bool(
        strong_candidates and (needs_replenishment or fresh_refill or hot_capture)
    )

    selected = strong_candidates[: config.max_videos_per_run] if should_process else []
    return {
        "shouldProcess": should_process,
        "reason": (
            "below_reorder_point"
            if needs_replenishment and selected
            else "hot_source_capture"
            if hot_capture and selected
            else "fresh_high_quality_refill"
            if fresh_refill and selected
            else "stock_healthy"
            if effective_stock > reorder
            else "no_eligible_source"
        ),
        "effectiveStockClips": round(effective_stock, 2),
        "reorderStockClips": reorder,
        "targetStockClips": target,
        "stockDeficitClips": deficit,
        "postsPerDay": config.posts_per_day,
        "candidateCount": len(ranked_candidates),
        "selectedVideoIds": [item["videoId"] for item in selected],
        "topCandidates": [
            {
                "videoId": item["videoId"],
                "title": item["title"],
                "score": round(item["selectionScore"], 4),
                "viewsPerHour": round(item["viewsPerHour"], 1),
                "ageHours": round(item["ageHours"], 1),
                "durationMinutes": round(item["durationSeconds"] / 60.0, 1),
            }
            for item in strong_candidates[:5]
        ],
    }


def write_plan(plan: dict, path: str | None) -> None:
    rendered = json.dumps(plan, ensure_ascii=False, indent=2)
    print("\n=== Operations plan ===")
    print(rendered)
    if path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Stock-aware Kirinuki source selector and runner.")
    parser.add_argument("--plan-only", action="store_true", help="Only evaluate stock and source candidates.")
    parser.add_argument("--plan-output", default="", help="Optional JSON file for the operations plan.")
    args = parser.parse_args()

    load_dotenv()
    config = OperationsConfig.from_env()

    deadline = Deadline(
        minutes=float(os.environ.get("KIRINUKI_BUDGET_MINUTES", "300")),
        min_video_minutes=float(os.environ.get("KIRINUKI_MIN_VIDEO_MINUTES", "40")),
    )

    required_vars = {
        "YOUTUBE_API_KEY": os.environ.get("YOUTUBE_API_KEY"),
        "GDRIVE_PARENT_FOLDER_ID": os.environ.get("GDRIVE_PARENT_FOLDER_ID"),
        "GDRIVE_CLIENT_SECRET_JSON": os.environ.get("GDRIVE_CLIENT_SECRET_JSON"),
        "GDRIVE_REFRESH_TOKEN": os.environ.get("GDRIVE_REFRESH_TOKEN"),
        "YOUTUBE_CHANNEL_ID": os.environ.get("YOUTUBE_CHANNEL_ID"),
    }
    if not args.plan_only:
        required_vars.update(
            {
                "RAPIDAPI_KEY": os.environ.get("RAPIDAPI_KEY"),
                "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
            }
        )

    missing_vars = [name for name, value in required_vars.items() if not value]
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}", file=sys.stderr)
        sys.exit(1)

    youtube_api_key = required_vars["YOUTUBE_API_KEY"]
    folder_id = required_vars["GDRIVE_PARENT_FOLDER_ID"]
    channel_id = required_vars["YOUTUBE_CHANNEL_ID"]

    drive_service = get_drive_service()
    processed_entries, processed_file_id = load_processed_videos(drive_service, folder_id)

    # The Drive folder is the physical posting stock. This includes clips created by
    # scheduled and manual runs alike; processed_videos.json remains the source ledger.
    clip_files = list_clip_files(drive_service, folder_id)
    preliminary_stock = estimate_drive_clip_stock(
        clip_files,
        posts_per_day=config.posts_per_day,
    )
    stock_source = "drive_mp4s"
    print(
        f"Drive stock: {len(clip_files)} clip file(s), "
        f"{preliminary_stock:.1f} effective after expected posting consumption."
    )

    processed_ids = {
        entry.get("videoId")
        for entry in processed_entries
        if entry.get("videoId") and not _is_retryable(entry)
    }

    playlist_id = get_uploads_playlist_id(youtube_api_key, channel_id)
    if not playlist_id:
        print("Could not resolve uploads playlist.", file=sys.stderr)
        sys.exit(1)

    videos = fetch_recent_videos(youtube_api_key, playlist_id, config.max_search_videos)
    source_diagnostics: dict = {}
    ranked_candidates = build_ranked_candidates(
        videos,
        processed_ids,
        config,
        diagnostics=source_diagnostics,
    )
    source_window = f"{config.max_source_age_days:g}d"

    if (
        not ranked_candidates
        and preliminary_stock < config.reorder_stock_clips
        and config.fallback_max_source_age_days > config.max_source_age_days
    ):
        print(
            "No preferred-window source while stock is critical; "
            f"expanding to {config.fallback_max_source_age_days:g} days and "
            f"up to {config.fallback_max_search_videos} uploads."
        )
        if config.fallback_max_search_videos > len(videos):
            videos = fetch_recent_videos(
                youtube_api_key,
                playlist_id,
                config.fallback_max_search_videos,
            )
        ranked_candidates = build_ranked_candidates(
            videos,
            processed_ids,
            config,
            max_source_age_days=config.fallback_max_source_age_days,
            diagnostics=source_diagnostics,
        )
        source_window = (
            f"{config.fallback_max_source_age_days:g}d/"
            f"{config.fallback_max_search_videos}-upload-fallback"
        )

    plan = make_plan(preliminary_stock, ranked_candidates, config)
    plan["stockSource"] = stock_source
    plan["sourceWindow"] = source_window
    plan["sourceDiagnostics"] = source_diagnostics
    write_plan(plan, args.plan_output or None)

    if args.plan_only:
        return

    if not plan["shouldProcess"]:
        print(f"No production run needed: {plan['reason']}.")
        return

    print(f"Run budget: {deadline.summary()}")
    print(
        f"Stock policy: {config.posts_per_day:g}/day, "
        f"reorder at {config.reorder_stock_clips}, target {config.target_stock_clips}."
    )

    attempts = 0
    for candidate in ranked_candidates:
        if attempts >= config.max_videos_per_run:
            print(f"Reached MAX_VIDEOS_PER_RUN={config.max_videos_per_run}.")
            break

        effective_stock = estimate_drive_clip_stock(
            list_clip_files(drive_service, folder_id),
            posts_per_day=config.posts_per_day,
        )
        if effective_stock >= config.target_stock_clips:
            print(
                f"Target stock reached ({effective_stock:.1f}/"
                f"{config.target_stock_clips}). Stopping."
            )
            break

        if (
            candidate["selectionScore"] < config.min_selection_score
            and effective_stock >= config.reorder_stock_clips
        ):
            print(
                f"Skipping low-score source {candidate['videoId']} "
                f"({candidate['selectionScore']:.3f})."
            )
            continue

        if not deadline.can_start_video():
            print(f"Not enough budget to start another video ({deadline.summary()}).")
            break

        video_id = candidate["videoId"]
        title = candidate["title"]
        attempts += 1

        cached_state, cached_file_id = load_state_from_drive(drive_service, folder_id, video_id)
        cached_status = cached_state.get("status")
        if cached_status == "completed":
            uploaded_count = int(cached_state.get("uploadedClips") or 0)
            processed_entries, processed_file_id = record_processed_entry(
                drive_service,
                folder_id,
                processed_entries,
                processed_file_id,
                video_id,
                title,
                "completed",
                metadata=selection_metadata(candidate, uploaded_count),
            )
            processed_ids.add(video_id)
            if cached_file_id:
                delete_file(drive_service, cached_file_id)
            continue

        hot_capture = (
            effective_stock <= config.target_stock_clips + 2
            and float(candidate.get("ageHours") or 999999) <= 18.0
            and float(candidate.get("selectionScore") or 0.0) >= 0.82
        )
        target_clips = clips_needed_for_source(
            effective_stock,
            config.target_stock_clips,
            config.clips_per_source_cap,
        )
        if target_clips <= 0 and hot_capture:
            # Preserve a couple of clips from an exceptional fresh source even when the
            # normal posting buffer is already full. This avoids inventory discipline
            # accidentally throwing away time-sensitive breakout content.
            target_clips = min(2, config.clips_per_source_cap)
        if target_clips <= 0:
            break

        print("\n=== Selected source ===")
        print(f"ID: {video_id}")
        print(f"Title: {title}")
        print(f"Selection score: {candidate['selectionScore']:.3f}")
        print(f"Views/hour: {candidate['viewsPerHour']:.1f}")
        print(f"Age: {candidate['ageHours']:.1f}h")
        print(f"Target clips from source: {target_clips}")

        resume_flag = cached_status in {"in-progress", "failed"}
        os.environ["SOURCE_VIDEO_TITLE"] = cached_state.get("sourceTitle") or title
        os.environ["SOURCE_VIDEO_PUBLISHED_AT"] = candidate.get("publishedAt") or ""
        os.environ["SOURCE_SELECTION_SCORE"] = str(candidate.get("selectionScore") or 0.0)
        os.environ["KIRINUKI_TARGET_CLIPS"] = str(target_clips)

        command = [sys.executable, "run_all.py", video_id, "--subs", "--reaction"]
        if resume_flag:
            command.append("--resume")
            print("Resuming processing based on remote state.")

        if not run_command(
            command,
            f"Processing video {video_id}",
            timeout=max(60.0, deadline.remaining()),
        ):
            state_snapshot, _ = load_state_from_drive(drive_service, folder_id, video_id)
            failure_reason = state_snapshot.get("failureReason") if state_snapshot else "pipeline"
            processed_entries, processed_file_id = record_processed_entry(
                drive_service,
                folder_id,
                processed_entries,
                processed_file_id,
                video_id,
                title,
                "failed",
                failure_reason or "pipeline",
                metadata=selection_metadata(candidate),
            )
            continue

        refreshed_state, refreshed_file_id = load_state_from_drive(
            drive_service, folder_id, video_id
        )
        refreshed_status = refreshed_state.get("status")
        if not refreshed_state:
            # Backward compatibility with older run_all.py versions that deleted state
            # immediately after success.
            refreshed_status = "completed"

        if refreshed_status != "completed":
            reason = refreshed_state.get("failureReason") if refreshed_state else "pipeline"
            processed_entries, processed_file_id = record_processed_entry(
                drive_service,
                folder_id,
                processed_entries,
                processed_file_id,
                video_id,
                title,
                refreshed_status or "failed",
                reason or "pipeline",
                metadata=selection_metadata(candidate),
            )
            continue

        uploaded_count = int(
            refreshed_state.get("uploadedClips")
            or refreshed_state.get("totalClips")
            or 0
        )
        print(f"Completed source with {uploaded_count} uploaded clip(s).")

        processed_entries, processed_file_id = record_processed_entry(
            drive_service,
            folder_id,
            processed_entries,
            processed_file_id,
            video_id,
            title,
            "completed",
            metadata=selection_metadata(candidate, uploaded_count),
        )
        processed_ids.add(video_id)

        # processed_videos.json is the durable operational ledger. Once the completion
        # receipt has been copied into it, the per-video state file is no longer needed.
        if refreshed_file_id:
            delete_file(drive_service, refreshed_file_id)

        updated_stock = estimate_drive_clip_stock(
            list_clip_files(drive_service, folder_id),
            posts_per_day=config.posts_per_day,
        )
        print(
            f"Effective posting stock after source: {updated_stock:.1f}/"
            f"{config.target_stock_clips} clips."
        )

    final_stock = estimate_drive_clip_stock(
        list_clip_files(drive_service, folder_id),
        posts_per_day=config.posts_per_day,
    )
    print(f"Final effective posting stock: {final_stock:.1f} clips.")


if __name__ == "__main__":
    main()
