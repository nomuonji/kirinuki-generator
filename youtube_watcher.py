import json
import os
import subprocess
import sys
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


def run_command(command, description):
    """Runs a command and prints its description, streaming output in real-time."""
    print(f"--- {description} ---")
    print("Executing:", " ".join(map(str, command)))

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    for line in iter(process.stdout.readline, ""):
        print(line, end="")
    process.stdout.close()
    return_code = process.wait()

    if return_code != 0:
        print(
            f"\nERROR during '{description}': Command returned non-zero exit status {return_code}.",
            file=sys.stderr,
        )
        return False

    print(f"\n--- Finished: {description} ---\n")
    return True


def get_latest_videos(api_key, channel_id):
    """Fetch latest videos from the specified YouTube channel."""
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        channel_request = youtube.channels().list(part="contentDetails", id=channel_id)
        channel_response = channel_request.execute()
        if not channel_response.get("items"):
            print(f"Channel not found for ID: {channel_id}")
            return []

        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        playlist_request = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=10,
        )
        playlist_response = playlist_request.execute()
        video_ids = [item["contentDetails"]["videoId"] for item in playlist_response.get("items", [])]
        if not video_ids:
            return []

        videos_request = youtube.videos().list(part="contentDetails,snippet", id=",".join(video_ids))
        videos_response = videos_request.execute()
        videos = sorted(videos_response.get("items", []), key=lambda x: x["snippet"]["publishedAt"], reverse=True)
        return videos
    except HttpError as exc:
        print(f"An HTTP error {exc.resp.status} occurred: {exc.content}")
        return []
    except Exception as exc:  # pylint: disable=broad-except
        print(f"An error occurred: {exc}")
        return []


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
    if existing:
        existing.update(record)
    else:
        entries.append(record)

    entries.sort(key=lambda entry: entry.get("processedAt", ""), reverse=True)
    file_id = save_processed_videos(service, folder_id, entries, file_id)
    return entries, file_id


def main():
    load_dotenv()

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
    processed_ids = {entry.get("videoId") for entry in processed_entries if entry.get("videoId")}
    print(f"Previously processed videos: {len(processed_entries)}")

    videos = get_latest_videos(youtube_api_key, youtube_channel_id)
    if not videos:
        print("No videos found or API error.")
        return

    candidates = [video for video in reversed(videos) if video["id"] not in processed_ids]
    if not candidates:
        print("No new videos to process.")
        return

    print(f"Found {len(candidates)} new video(s) to process.")

    for video in candidates:
        video_id = video["id"]
        title = video["snippet"]["title"]
        duration = parse_duration(video["contentDetails"]["duration"])

        print("\n--- Checking Video ---")
        print(f"ID: {video_id}")
        print(f"Title: {title}")
        print(f"Duration: {duration.total_seconds()}s")

        if duration.total_seconds() < MIN_VIDEO_DURATION_SECONDS:
            print("Video is shorter than the minimum duration. Skipping.")
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

        if not run_command(command, f"Processing video {video_id}"):
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
        break


if __name__ == "__main__":
    main()
