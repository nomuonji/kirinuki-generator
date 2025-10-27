
import os
import sys
import subprocess
import json
import re
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload

# --- Configuration ---
YOUTUBE_CHANNEL_ID = "UCzXVsEc1h2Elljge0fnQYRg"
MIN_VIDEO_DURATION_SECONDS = 360  # 6 minutes
STATE_FILE = Path("last_video_id.txt")

def run_command(command, description):
    """Runs a command and prints its description, streaming output in real-time."""
    print(f"--- {description} ---")
    cmd_str = ' '.join(map(str, command))
    print(f"Executing: {cmd_str}")

    try:
        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Redirect stderr to stdout
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        # Read and print output line by line
        for line in iter(process.stdout.readline, ''):
            print(line, end='')

        process.stdout.close()
        return_code = process.wait()

        if return_code != 0:
            # Create a CalledProcessError-like object for consistent error handling
            raise subprocess.CalledProcessError(return_code, command)

        print(f"\n--- Finished: {description} ---\n")
        return True

    except subprocess.CalledProcessError as e:
        # Error message is now more generic as stdout/stderr is already printed
        print(f"\nERROR during '{description}': Command returned non-zero exit status {e.returncode}.", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"\nERROR: Command not found for '{description}': {command[0]}", file=sys.stderr)
        return False

def get_latest_videos(api_key, channel_id):
    """Get latest videos from a YouTube channel."""
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
            maxResults=10
        )
        playlist_response = playlist_request.execute()
        video_ids = [item["contentDetails"]["videoId"] for item in playlist_response.get("items", [])]
        if not video_ids:
            return []
        videos_request = youtube.videos().list(part="contentDetails,snippet", id=",".join(video_ids))
        videos_response = videos_request.execute()
        videos = sorted(videos_response.get("items", []), key=lambda x: x['snippet']['publishedAt'], reverse=True)
        return videos
    except HttpError as e:
        print(f"An HTTP error {e.resp.status} occurred: {e.content}")
        return []
    except Exception as e:
        print(f"An error occurred: {e}")
        return []

def parse_duration(duration_str):
    """Parses ISO 8601 duration format."""
    if not duration_str.startswith('PT'): return timedelta(0)
    duration_str = duration_str[2:]
    total_seconds = 0
    number_buffer = ""
    for char in duration_str:
        if char.isdigit():
            number_buffer += char
        elif char == 'H':
            total_seconds += int(number_buffer) * 3600
            number_buffer = ""
        elif char == 'M':
            total_seconds += int(number_buffer) * 60
            number_buffer = ""
        elif char == 'S':
            total_seconds += int(number_buffer)
            number_buffer = ""
    return timedelta(seconds=total_seconds)

def get_last_processed_video_id():
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return None

def set_last_processed_video_id(video_id):
    STATE_FILE.write_text(video_id)

def sanitize_filename(name: str) -> str:
    """Remove invalid characters and collapse whitespace for a safe base filename."""
    if not isinstance(name, str):
        name = str(name or "")
    # Replace unsupported characters, collapse whitespace
    sanitized = re.sub(r'[<>:"/\\|?*]', "", name)
    sanitized = re.sub(r"[\r\n\t]+", " ", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "clip"


def build_safe_filename(base: str, suffix: str, max_bytes: int = 240) -> str:
    """
    Combine base and suffix ensuring the resulting filename stays under the byte limit.
    ext4 / NTFS allow 255 bytes per filename; keep a buffer for safety.
    """
    base = base.strip() or "clip"
    suffix = suffix.strip()
    candidate = f"{base}{suffix}"
    if len(candidate.encode("utf-8")) <= max_bytes:
        return candidate

    # Trim the base until the encoded byte length fits within max_bytes.
    encoded_suffix = suffix.encode("utf-8")
    budget = max_bytes - len(encoded_suffix)
    truncated = []
    consumed = 0
    for ch in base:
        ch_bytes = ch.encode("utf-8")
        if consumed + len(ch_bytes) > budget:
            break
        truncated.append(ch)
        consumed += len(ch_bytes)

    safe_base = "".join(truncated).rstrip() or "clip"
    return f"{safe_base}{suffix}"

def get_gdrive_credentials():
    """Gets Google Drive credentials from token file, refreshing if necessary."""
    creds = None
    token_file = 'gdrive_token.json'
    scopes = ["https://www.googleapis.com/auth/drive"]

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Credentials expired. Refreshing token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}", file=sys.stderr)
                raise Exception("Could not refresh token. Please re-run authenticate_gdrive.py.")
        else:
            raise FileNotFoundError(
                f"'{token_file}' not found or invalid. "
                "Please run authenticate_gdrive.py to generate it."
            )

        with open(token_file, 'w') as token:
            token.write(creds.to_json())
            print(f"Token refreshed and saved to {token_file}")

    return creds

def rename_and_upload_files(video_title, parent_folder_id):
    """Renames output files with the video title and uploads them to Google Drive."""
    print("--- Renaming and Uploading to Google Drive ---")
    base_title = sanitize_filename(video_title)
    rendered_dir = Path("rendered")
    props_dir = Path("apps/remotion/public/props")
    
    # --- Rename files ---
    renamed_files = []
    try:
        video_files = sorted(list(rendered_dir.glob('*.mp4')))
        prop_files = sorted(list(props_dir.glob('*.json')))

        for i, file_path in enumerate(video_files):
            suffix = f"_clip_{i+1:02d}.mp4"
            new_name = build_safe_filename(base_title, suffix)
            new_path = file_path.with_name(new_name)
            file_path.rename(new_path)
            renamed_files.append(new_path)
            print(f"Renamed {file_path.name} to {new_name}")

        for i, file_path in enumerate(prop_files):
            if file_path.name.startswith('clip_'):
                suffix = f"_clip_{i+1:02d}.json"
                new_name = build_safe_filename(base_title, suffix)
                new_path = file_path.with_name(new_name)
                file_path.rename(new_path)
                renamed_files.append(new_path)
                print(f"Renamed {file_path.name} to {new_name}")

    except Exception as e:
        print(f"ERROR during file renaming: {e}")
        return False

    # --- Upload files ---
    creds = get_gdrive_credentials()
    drive_service = build('drive', 'v3', credentials=creds)

    if not renamed_files:
        print("No files found to upload.")
        return True

    print(f"Uploading {len(renamed_files)} file(s) to Google Drive folder ID: {parent_folder_id}")
    # Threshold for switching to resumable uploads (5MB)
    RESUMABLE_UPLOAD_THRESHOLD = 5 * 1024 * 1024

    for file_path in renamed_files:
        print(f"\nProcessing upload for: {file_path.name}...")
        try:
            file_size = file_path.stat().st_size
            file_metadata = {'name': file_path.name, 'parents': [parent_folder_id]}

            # Use resumable upload for large files, simple upload for smaller files
            if file_size > RESUMABLE_UPLOAD_THRESHOLD:
                print(f"  File size ({file_size / 1024**2:.2f} MB) is large, using resumable upload.")
                media = MediaFileUpload(str(file_path), resumable=True)
                request = drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                )

                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        print(f"  Uploaded {int(status.progress() * 100)}%")
            else:
                print(f"  File size ({file_size / 1024:.2f} KB) is small, using simple upload.")
                media = MediaFileUpload(str(file_path))
                drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()

            print(f"Successfully uploaded {file_path.name}.")

        except HttpError as e:
            print(f"An HTTP error occurred during upload of {file_path.name}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"An unexpected error occurred during upload of {file_path.name}: {e}", file=sys.stderr)

    print("\n--- All file uploads attempted. Proceeding... ---")
    return True

def main():
    """Main function to check for videos and process them."""
    load_dotenv()

    required_vars = {
        "YOUTUBE_API_KEY": os.environ.get("YOUTUBE_API_KEY"),
        "GDRIVE_PARENT_FOLDER_ID": os.environ.get("GDRIVE_PARENT_FOLDER_ID"),
        "RAPIDAPI_KEY": os.environ.get("RAPIDAPI_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "GDRIVE_CLIENT_SECRET_JSON": os.environ.get("GDRIVE_CLIENT_SECRET_JSON"),
        "GDRIVE_REFRESH_TOKEN": os.environ.get("GDRIVE_REFRESH_TOKEN"),
    }

    missing_vars = [name for name, value in required_vars.items() if not value]
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}", file=sys.stderr)
        sys.exit(1)

    youtube_api_key = required_vars["YOUTUBE_API_KEY"]
    gdrive_parent_folder_id = required_vars["GDRIVE_PARENT_FOLDER_ID"]
    gdrive_client_secret_json = required_vars["GDRIVE_CLIENT_SECRET_JSON"]
    gdrive_refresh_token = required_vars["GDRIVE_REFRESH_TOKEN"]

    # --- Create credential files from environment variables ---
    try:
        # Create client_secret.json
        client_secret_data = json.loads(gdrive_client_secret_json)
        with open('client_secret.json', 'w') as f:
            json.dump(client_secret_data, f)

        # Determine key ('web' or 'installed') and get client data
        client_info = client_secret_data.get('web') or client_secret_data.get('installed')
        if not client_info:
            raise ValueError("Invalid client secret format: 'web' or 'installed' key not found.")

        # Create gdrive_token.json from refresh token
        token_data = {
            "token": None,  # Access token is not needed, will be fetched
            "refresh_token": gdrive_refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "scopes": ["https://www.googleapis.com/auth/drive"],
            "expiry": "1970-01-01T00:00:00Z" # Force refresh
        }
        with open('gdrive_token.json', 'w') as f:
            json.dump(token_data, f)

        print("Successfully created Google Drive credential files from environment variables.")

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"ERROR: Failed to parse Google Drive credentials from environment variables: {e}", file=sys.stderr)
        sys.exit(1)

    last_processed_id = get_last_processed_video_id()
    print(f"Last processed video ID: {last_processed_id}")

    videos = get_latest_videos(youtube_api_key, YOUTUBE_CHANNEL_ID)
    
    if not videos:
        print("No videos found or API error.")
        sys.exit(0)

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
        sys.exit(0)

    new_videos_to_process.reverse()

    print(f"Found {len(new_videos_to_process)} new video(s) to process.")

    # Iterate through new videos and process the first one that meets the criteria
    processed_one_video = False
    for video in new_videos_to_process:
        video_id = video["id"]
        title = video["snippet"]["title"]
        duration = parse_duration(video["contentDetails"]["duration"])

        print(f"\n--- Checking Video ---")
        print(f"ID: {video_id}")
        print(f"Title: {title}")
        print(f"Duration: {duration.total_seconds()}s")

        if duration.total_seconds() < MIN_VIDEO_DURATION_SECONDS:
            print("Video is shorter than the minimum duration. Skipping.")
            set_last_processed_video_id(video_id)
            continue  # Move to the next video

        # Found a video to process
        print("--- Starting processing for this video ---")
        process_command = [sys.executable, "run_all.py", video_id, "--subs", "--reaction"]
        
        if run_command(process_command, f"Processing video {video_id}"):
            print(f"Successfully processed video {video_id}.")

            try:
                print("Attempting to rename and upload files...")
                upload_success = rename_and_upload_files(title, gdrive_parent_folder_id)
                print("Finished rename and upload step.")

                if upload_success:
                    print("Upload successful.")
                    set_last_processed_video_id(video_id)
                    print(f"Updated last processed video ID to: {video_id}")
                else:
                    print("Upload failed. State file will not be updated.", file=sys.stderr)
                    # Even if upload fails, we stop after one attempt
                    sys.exit(1)
            except Exception as e:
                print("--- AN UNEXPECTED ERROR OCCURRED DURING UPLOAD ---", file=sys.stderr)
                print(f"An error of type {type(e).__name__} occurred: {e}", file=sys.stderr)
                traceback.print_exc()
                sys.exit(1)
        else:
            print(f"Failed to process video {video_id}. Stopping.")
            sys.exit(1)

        # Mark that we've processed one video and exit the loop
        processed_one_video = True
        break

    if not processed_one_video:
        print("No new videos met the processing criteria in this run.")

if __name__ == "__main__":
    main()
