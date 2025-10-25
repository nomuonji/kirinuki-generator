
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
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaFileUpload

# --- Configuration ---
YOUTUBE_CHANNEL_ID = "UCzXVsEc1h2Elljge0fnQYRg"
MIN_VIDEO_DURATION_SECONDS = 360  # 6 minutes
STATE_FILE = Path("last_video_id.txt")

def run_command(command, description):
    """Runs a command and prints its description."""
    print(f"--- {description} ---")
    cmd_str = ' '.join(map(str, command))
    print(f"Executing: {cmd_str}")
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        print(result.stdout)
        print(f"--- Finished: {description} ---\n")
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR during '{description}':")
        print(e.stdout)
        print(e.stderr)
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

def sanitize_filename(name):
    """Remove invalid characters from a string to make it a valid filename."""
    # Remove invalid chars
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # Limit length
    return name[:100].strip()

def rename_and_upload_files(video_title, service_account_info, parent_folder_id):
    """Renames output files with the video title and uploads them to Google Drive."""
    print("--- Renaming and Uploading to Google Drive ---")
    sanitized_title = sanitize_filename(video_title)
    rendered_dir = Path("rendered")
    props_dir = Path("apps/remotion/public/props")
    
    # --- Rename files ---
    renamed_files = []
    try:
        # Sort files to maintain order
        video_files = sorted(list(rendered_dir.glob('*.mp4')))
        prop_files = sorted(list(props_dir.glob('*.json')))

        for i, file_path in enumerate(video_files):
            new_name = f"{sanitized_title}_clip_{i+1:02d}.mp4"
            new_path = file_path.with_name(new_name)
            file_path.rename(new_path)
            renamed_files.append(new_path)
            print(f"Renamed {file_path.name} to {new_name}")

        for i, file_path in enumerate(prop_files):
            # Ensure it's a clip prop, not the main temp_props
            if file_path.name.startswith('clip_'):
                new_name = f"{sanitized_title}_clip_{i+1:02d}.json"
                new_path = file_path.with_name(new_name)
                file_path.rename(new_path)
                renamed_files.append(new_path)
                print(f"Renamed {file_path.name} to {new_name}")

    except Exception as e:
        print(f"ERROR during file renaming: {e}")
        return False

    # --- Upload files ---
    # No try/except here, let it bubble up to the main handler
    creds = Credentials.from_service_account_info(service_account_info, scopes=["https://www.googleapis.com/auth/drive"])
    drive_service = build('drive', 'v3', credentials=creds)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_folder_name = f"{sanitized_title}_{timestamp}"

    file_metadata = {
        'name': run_folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_folder_id]
    }
    run_folder = drive_service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
    run_folder_id = run_folder.get('id')
    print(f"Created Google Drive folder: '{run_folder_name}' (ID: {run_folder_id})")

    if not renamed_files:
        print("No files found to upload.")
        return True # Nothing to upload is not a failure

    for file_path in renamed_files:
        print(f"Uploading {file_path.name}...")
        file_metadata = {'name': file_path.name, 'parents': [run_folder_id]}
        media = MediaFileUpload(str(file_path))
        drive_service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
        print(f"Successfully uploaded {file_path.name}.")

    return True

def main():
    """Main function to check for videos and process them."""
    load_dotenv()

    required_vars = {
        "YOUTUBE_API_KEY": os.environ.get("YOUTUBE_API_KEY"),
        "GDRIVE_CREDENTIALS_JSON": os.environ.get("GDRIVE_CREDENTIALS_JSON"),
        "GDRIVE_PARENT_FOLDER_ID": os.environ.get("GDRIVE_PARENT_FOLDER_ID"),
        "RAPIDAPI_KEY": os.environ.get("RAPIDAPI_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
    }

    missing_vars = [name for name, value in required_vars.items() if not value]
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}", file=sys.stderr)
        sys.exit(1)

    youtube_api_key = required_vars["YOUTUBE_API_KEY"]
    gdrive_creds_json = required_vars["GDRIVE_CREDENTIALS_JSON"]
    gdrive_parent_folder_id = required_vars["GDRIVE_PARENT_FOLDER_ID"]

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

    for video in new_videos_to_process:
        video_id = video["id"]
        title = video["snippet"]["title"]
        duration = parse_duration(video["contentDetails"]["duration"])

        print(f"\n--- Processing Video ---")
        print(f"ID: {video_id}")
        print(f"Title: {title}")
        print(f"Duration: {duration.total_seconds()}s")

        if duration.total_seconds() < MIN_VIDEO_DURATION_SECONDS:
            print("Video is shorter than the minimum duration. Skipping.")
            set_last_processed_video_id(video_id)
            continue

        process_command = [sys.executable, "run_all.py", video_id, "--subs", "--reaction"]
        
        if run_command(process_command, f"Processing video {video_id}"):
            print(f"Successfully processed video {video_id}.")
            
            try:
                print("Attempting to parse Google Drive credentials...")
                gdrive_creds = json.loads(gdrive_creds_json)
                print("Successfully parsed Google Drive credentials.")

                print("Attempting to rename and upload files...")
                upload_success = rename_and_upload_files(title, gdrive_creds, gdrive_parent_folder_id)
                print("Finished rename and upload step.")

                if upload_success:
                    print("Upload successful.")
                    set_last_processed_video_id(video_id)
                    print(f"Updated last processed video ID to: {video_id}")
                else:
                    print("Upload failed. State file will not be updated.", file=sys.stderr)
                    sys.exit(1)
            except Exception as e:
                print("--- AN UNEXPECTED ERROR OCCURRED DURING UPLOAD ---", file=sys.stderr)
                if isinstance(e, json.JSONDecodeError):
                    print("ERROR: Failed to parse GDRIVE_CREDENTIALS_JSON. Please ensure it's a valid, single-line JSON string in your repository secrets.", file=sys.stderr)
                else:
                    print(f"An error of type {type(e).__name__} occurred.", file=sys.stderr)

                # Print the full traceback for detailed debugging
                traceback.print_exc()
                sys.exit(1)
        else:
            print(f"Failed to process video {video_id}. Stopping.")
            sys.exit(1)

if __name__ == "__main__":
    main()
