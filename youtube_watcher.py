import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from packages.shared.gdrive import (
    download_file_bytes,
    find_file,
    get_drive_service,
    upload_json_data,
)

MIN_VIDEO_DURATION_SECONDS = 360  # 6 minutes
PROCESSED_LOG_NAME = "processed_videos.json"

# A transient failure is retried, but only a few times and never twice in the same day, so a
# systemically broken step (expired cookies, a yt-dlp the site has outgrown) can no longer
# burn a whole run's worth of time re-failing on every candidate video.
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_HOURS = (6, 24, 72)

# Failures that will never resolve on their own. Retrying them wastes the entire budget.
PERMANENT_FAILURE_REASONS = {"transcript", "duration_too_short"}

# A failure older than this is abandoned rather than retried: the clip has lost its news
# value, and chasing the backlog would starve newly published videos.
STALE_FAILURE_DAYS = 30


def _older_than(timestamp: str | None, days: int) -> bool:
    if not timestamp:
        return False
    try:
        when = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - when > timedelta(days=days)


def _is_retryable(entry: dict) -> bool:
    """Decides whether a previously-seen video should be attempted again."""
    status = entry.get("status")
    if status not in {"failed", "in-progress"}:
        return False  # completed / skipped / unknown -> leave alone

    if entry.get("reason") in PERMANENT_FAILURE_REASONS:
        return False

    last_attempt = entry.get("processedAt")
    if _older_than(last_attempt, STALE_FAILURE_DAYS):
        # The pipeline was broken from 2025-12 to 2026-07, leaving a backlog of failures.
        # Clips are worth most soon after a video is published, so working through
        # months-old misses would starve new uploads for weeks. Let them go.
        return False

    attempts = int(entry.get("attempts") or 1)
    if attempts >= MAX_RETRY_ATTEMPTS:
        return False

    last_attempt = entry.get("processedAt")
    if not last_attempt:
        return True
    try:
        last = datetime.fromisoformat(last_attempt.replace("Z", "+00:00"))
    except ValueError:
        return True

    backoff = RETRY_BACKOFF_HOURS[min(attempts, len(RETRY_BACKOFF_HOURS)) - 1]
    return datetime.now(timezone.utc) - last >= timedelta(hours=backoff)


class Deadline:
    """
    Wall-clock budget for a single watcher run.

    GitHub Actions kills a job at 6 hours with no chance to record anything. Finishing
    voluntarily before that means the run ends cleanly, state is written to Drive, and the
    next run resumes instead of starting over.
    """

    def __init__(self, minutes: float, min_video_minutes: float):
        self._end = time.monotonic() + minutes * 60
        self._min_video_seconds = min_video_minutes * 60

    def remaining(self) -> float:
        return self._end - time.monotonic()

    def exhausted(self) -> bool:
        return self.remaining() <= 0

    def can_start_video(self) -> bool:
        """Refuses to begin a video we almost certainly cannot finish."""
        return self.remaining() >= self._min_video_seconds

    def summary(self) -> str:
        remaining = max(0.0, self.remaining())
        return f"{remaining / 60:.1f} min remaining"


def run_command(command, description, timeout=None):
    """Runs a command and prints its description, streaming output in real-time."""
    print(f"--- {description} ---")
    print("Executing:", " ".join(map(str, command)))

    # PYTHONUNBUFFERED: Python block-buffers stdout when it is a pipe, so anything still
    # in the buffer is lost when we kill a hung child. That is how a five-hour hang
    # produced zero diagnostic output.
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
    """Retrieve the uploads playlist ID for the given channel."""
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        channel_request = youtube.channels().list(part="contentDetails", id=channel_id)
        channel_response = channel_request.execute()
        if not channel_response.get("items"):
            print(f"Channel not found for ID: {channel_id}")
            return None
        return channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except HttpError as exc:
        print(f"HTTP error retrieving channel info: {exc}")
        return None


def fetch_videos_batch(api_key, playlist_id, page_token=None, max_results=10):
    """Fetch a batch of videos from the playlist, returning (videos, next_page_token)."""
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        playlist_request = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=max_results,
            pageToken=page_token
        )
        playlist_response = playlist_request.execute()
        
        video_ids = [item["contentDetails"]["videoId"] for item in playlist_response.get("items", [])]
        next_page_token = playlist_response.get("nextPageToken")

        if not video_ids:
            return [], next_page_token

        videos_request = youtube.videos().list(part="contentDetails,snippet", id=",".join(video_ids))
        videos_response = videos_request.execute()
        
        # Sort by publishedAt (newest first)
        videos = sorted(videos_response.get("items", []), key=lambda x: x["snippet"]["publishedAt"], reverse=True)
        return videos, next_page_token

    except HttpError as exc:
        print(f"An HTTP error {exc.resp.status} occurred: {exc.content}")
        return [], None
    except Exception as exc:
        print(f"An error occurred: {exc}")
        return [], None


def parse_duration(duration_str):
    """Parses ISO 8601 duration format to timedelta."""
    if not duration_str.startswith("PT"):
        return timedelta(0)

    duration_str = duration_str[2:]
    total_seconds = 0
    number_buffer = ""

    for char in duration_str:
        if char.isdigit():
            number_buffer += char
        elif char == "H":
            total_seconds += int(number_buffer) * 3600
            number_buffer = ""
        elif char == "M":
            total_seconds += int(number_buffer) * 60
            number_buffer = ""
        elif char == "S":
            total_seconds += int(number_buffer)
            number_buffer = ""

    return timedelta(seconds=total_seconds)


def load_state_from_drive(service, folder_id: str, video_id: str) -> tuple[dict, str | None]:
    """Loads state JSON from Drive, returning (state_dict, drive_file_id)."""
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
) -> tuple[list[dict], str | None]:
    record = {
        "videoId": video_id,
        "title": title,
        "processedAt": _now_iso(),
        "status": status,
    }
    if reason:
        record["reason"] = reason

    existing = next((entry for entry in entries if entry.get("videoId") == video_id), None)
    if status == "failed":
        # Count attempts so _is_retryable can eventually give up on a video.
        record["attempts"] = int((existing or {}).get("attempts") or 0) + 1

    if existing:
        existing.update(record)
    else:
        entries.append(record)

    entries.sort(key=lambda entry: entry.get("processedAt", ""), reverse=True)
    file_id = save_processed_videos(service, folder_id, entries, file_id)
    return entries, file_id


def main():
    load_dotenv()

    deadline = Deadline(
        minutes=float(os.environ.get("KIRINUKI_BUDGET_MINUTES", "300")),
        min_video_minutes=float(os.environ.get("KIRINUKI_MIN_VIDEO_MINUTES", "40")),
    )
    print(f"Run budget: {deadline.summary()}")

    required_vars = {
        "YOUTUBE_API_KEY": os.environ.get("YOUTUBE_API_KEY"),
        "GDRIVE_PARENT_FOLDER_ID": os.environ.get("GDRIVE_PARENT_FOLDER_ID"),
        "RAPIDAPI_KEY": os.environ.get("RAPIDAPI_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "GDRIVE_CLIENT_SECRET_JSON": os.environ.get("GDRIVE_CLIENT_SECRET_JSON"),
        "GDRIVE_REFRESH_TOKEN": os.environ.get("GDRIVE_REFRESH_TOKEN"),
        "YOUTUBE_CHANNEL_ID": os.environ.get("YOUTUBE_CHANNEL_ID"),
    }

    missing_vars = [name for name, value in required_vars.items() if not value]
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}", file=sys.stderr)
        sys.exit(1)

    youtube_api_key = required_vars["YOUTUBE_API_KEY"]
    gdrive_parent_folder_id = required_vars["GDRIVE_PARENT_FOLDER_ID"]
    youtube_channel_id = required_vars["YOUTUBE_CHANNEL_ID"]

    drive_service = get_drive_service()

    processed_entries, processed_file_id = load_processed_videos(drive_service, gdrive_parent_folder_id)
    # Every video we have already seen is skipped, failures included. Retrying failures
    # unconditionally meant a broken download made each run chew through every candidate
    # until the GitHub Actions 6-hour ceiling killed it, every day, producing nothing.
    # A failed video is retried by clearing its entry (see MAX_RETRY_ATTEMPTS below).
    processed_ids = {
        entry.get("videoId")
        for entry in processed_entries
        if entry.get("videoId") and not _is_retryable(entry)
    }
    print(f"Previously processed videos: {len(processed_entries)} (retryable: {len(processed_entries) - len(processed_ids)})")

    uploads_playlist_id = get_uploads_playlist_id(youtube_api_key, youtube_channel_id)
    if not uploads_playlist_id:
        print("Could not resolve uploads playlist. Exiting.")
        return

    page_token = None
    videos_checked = 0
    MAX_SEARCH_VIDEOS = 20  # Approximately 2 batches of 10

    # Loop to fetch batches until we find a target to process or hit the limit
    while videos_checked < MAX_SEARCH_VIDEOS:
        if deadline.exhausted():
            print(f"\nTime budget exhausted ({deadline.summary()}). Stopping.")
            break

        print(f"\nFetching video batch (checked {videos_checked}/{MAX_SEARCH_VIDEOS})...")
        videos, next_page_token = fetch_videos_batch(youtube_api_key, uploads_playlist_id, page_token=page_token)
        
        if not videos:
            print("No videos returned in this batch.")
            if not next_page_token:
                break
            page_token = next_page_token
            continue

        # Newest first. A clip is worth most shortly after the source video is published,
        # so a fresh upload should never wait behind older ones. (`videos` is already
        # sorted newest-first by fetch_videos_batch.)
        candidates = [video for video in videos if video["id"] not in processed_ids]
        
        if not candidates:
            print("All videos in this batch have been processed already.")
            if not next_page_token:
                print("No more pages available.")
                break
            page_token = next_page_token
            videos_checked += len(videos)
            continue

        print(f"Found {len(candidates)} candidate(s) in this batch.")
        
        found_target = False
        for video in candidates:
            video_id = video["id"]
            title = video["snippet"]["title"]
            duration = parse_duration(video["contentDetails"]["duration"])

            if not deadline.can_start_video():
                # Starting a video we cannot finish just burns the remainder of the run and
                # leaves a half-done state behind.
                print(f"\nNot enough budget to start another video ({deadline.summary()}).")
                found_target = True  # stop the outer paging loop too
                break

            print("\n--- Checking Video ---")
            print(f"ID: {video_id}")
            print(f"Title: {title}")
            print(f"Duration: {duration.total_seconds()}s")

            if duration.total_seconds() < MIN_VIDEO_DURATION_SECONDS:
                print("Video is shorter than the minimum duration. Skipping.")
                processed_entries, processed_file_id = record_processed_entry(
                    drive_service,
                    gdrive_parent_folder_id,
                    processed_entries,
                    processed_file_id,
                    video_id,
                    title,
                    "skipped",
                    "duration_too_short"
                )
                processed_ids.add(video_id)
                continue

            cached_state, _file_id = load_state_from_drive(drive_service, gdrive_parent_folder_id, video_id)
            cached_status = cached_state.get("status")
            if cached_status == "completed":
                print("Remote state indicates this video is already processed. Skipping.")
                if video_id not in processed_ids:
                    processed_entries.append({
                        "videoId": video_id,
                        "title": title,
                        "processedAt": cached_state.get("lastUpdated") or _now_iso(),
                    })
                    processed_file_id = save_processed_videos(drive_service, gdrive_parent_folder_id, processed_entries, processed_file_id)
                    processed_ids.add(video_id)
                continue

            resume_flag = cached_status in {"in-progress", "failed"}
            os.environ["SOURCE_VIDEO_TITLE"] = cached_state.get("sourceTitle") or title

            command = [
                sys.executable,
                "run_all.py",
                video_id,
                "--subs",
                "--reaction",
            ]
            if resume_flag:
                command.append("--resume")
                print("Resuming processing based on remote state.")

            # Hand the child the remaining budget so it is killed before GitHub Actions
            # would kill the whole job.
            if not run_command(
                command,
                f"Processing video {video_id}",
                timeout=max(60.0, deadline.remaining()),
            ):
                state_snapshot, _ = load_state_from_drive(drive_service, gdrive_parent_folder_id, video_id)
                failure_reason = state_snapshot.get("failureReason") if state_snapshot else "pipeline"
                processed_entries, processed_file_id = record_processed_entry(
                    drive_service,
                    gdrive_parent_folder_id,
                    processed_entries,
                    processed_file_id,
                    video_id,
                    title,
                    "failed",
                    failure_reason or "pipeline",
                )
                continue

            refreshed_state, _ = load_state_from_drive(drive_service, gdrive_parent_folder_id, video_id)
            refreshed_status = refreshed_state.get("status")
            # run_all.py deletes the state file upon successful completion, so an empty
            # state (no file) combined with a successful command exit means "completed".
            if not refreshed_state:
                # State file was deleted, which indicates run_all.py finished successfully
                refreshed_status = "completed"
            if refreshed_status != "completed":
                reason = refreshed_state.get("failureReason") if refreshed_state else "pipeline"
                processed_entries, processed_file_id = record_processed_entry(
                    drive_service,
                    gdrive_parent_folder_id,
                    processed_entries,
                    processed_file_id,
                    video_id,
                    title,
                    refreshed_status or "failed",
                    reason or "",
                )
                continue

            uploaded_count = refreshed_state.get("uploadedClips")
            if uploaded_count is not None:
                print(f"Total clips uploaded so far: {uploaded_count}")

            processed_entries, processed_file_id = record_processed_entry(
                drive_service,
                gdrive_parent_folder_id,
                processed_entries,
                processed_file_id,
                video_id,
                title,
                "completed",
            )
            processed_ids.add(video_id)
            print(f"Recorded completion of video {video_id} to Drive log.")
            found_target = True
            break
        
        if found_target:
            break
        
        # Prepare for next batch
        videos_checked += len(videos)
        page_token = next_page_token
        if not page_token:
            print("Reached end of playlist.")
            break


if __name__ == "__main__":
    main()
