import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from packages.shared.gdrive import (
    download_file_bytes,
    find_file,
    get_drive_service,
)

MIN_VIDEO_DURATION_SECONDS = 360  # 6 minutes


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


def get_last_processed_video_id(state_file):
    state_file = Path(state_file)
    if state_file.exists():
        return state_file.read_text().strip()
    return None


def set_last_processed_video_id(video_id, state_file):
    Path(state_file).write_text(video_id)


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


def main():
    load_dotenv()

    state_file_path = os.environ.get("STATE_FILE_PATH", "last_video_id.txt")
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

    last_processed_id = get_last_processed_video_id(state_file_path)
    print(f"Last processed video ID: {last_processed_id}")

    videos = get_latest_videos(youtube_api_key, youtube_channel_id)
    if not videos:
        print("No videos found or API error.")
        return

    new_videos_to_process = []
    found_last_processed = last_processed_id is None
    for video in videos:
        video_id = video["id"]
        if video_id == last_processed_id:
            found_last_processed = True
            break
        new_videos_to_process.append(video)

    if not found_last_processed:
        print("Last processed video not found in the latest 10 videos.")

    if not new_videos_to_process:
        print("No new videos to process.")
        return

    new_videos_to_process.reverse()
    print(f"Found {len(new_videos_to_process)} new video(s) to process.")

    for video in new_videos_to_process:
        video_id = video["id"]
        title = video["snippet"]["title"]
        duration = parse_duration(video["contentDetails"]["duration"])

        print("\n--- Checking Video ---")
        print(f"ID: {video_id}")
        print(f"Title: {title}")
        print(f"Duration: {duration.total_seconds()}s")

        if duration.total_seconds() < MIN_VIDEO_DURATION_SECONDS:
            print("Video is shorter than the minimum duration. Skipping.")
            set_last_processed_video_id(video_id, state_file_path)
            continue

        cached_state, _file_id = load_state_from_drive(drive_service, gdrive_parent_folder_id, video_id)
        cached_status = cached_state.get("status")
        if cached_status == "completed":
            print("Remote state indicates this video is already processed. Marking as completed and skipping.")
            set_last_processed_video_id(video_id, state_file_path)
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
            print(f"Failed to process video {video_id}. Stopping.")
            sys.exit(1)

        refreshed_state, _ = load_state_from_drive(drive_service, gdrive_parent_folder_id, video_id)
        refreshed_status = refreshed_state.get("status")
        if refreshed_status != "completed":
            print(
                f"Video {video_id} not fully processed yet (status={refreshed_status}). "
                "Stopping so the next workflow run can resume.",
                file=sys.stderr,
            )
            sys.exit(0)

        uploaded_count = refreshed_state.get("uploadedClips")
        if uploaded_count is not None:
            print(f"Total clips uploaded so far: {uploaded_count}")

        set_last_processed_video_id(video_id, state_file_path)
        print(f"Updated last processed video ID to: {video_id}")
        break


if __name__ == "__main__":
    main()
