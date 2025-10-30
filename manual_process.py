
import os
import sys
import json
import traceback
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Import necessary functions from youtube_watcher
from youtube_watcher import run_command, rename_and_upload_files, get_gdrive_credentials

def get_video_title(api_key, video_id):
    """Get the title of a single YouTube video."""
    print(f"--- Getting title for video ID: {video_id} ---")
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        videos_request = youtube.videos().list(part="snippet", id=video_id)
        videos_response = videos_request.execute()
        if not videos_response.get("items"):
            print(f"ERROR: Video not found for ID: {video_id}", file=sys.stderr)
            return None
        title = videos_response["items"][0]["snippet"]["title"]
        print(f"Found video title: {title}")
        return title
    except HttpError as e:
        print(f"An HTTP error {e.resp.status} occurred: {e.content}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"An unexpected error occurred while fetching video title: {e}", file=sys.stderr)
        traceback.print_exc()
        return None

def main():
    """Main function to process a single video."""
    load_dotenv()

    if len(sys.argv) < 3:
        print("Usage: python manual_process.py <video_id> <gdrive_folder_id>", file=sys.stderr)
        sys.exit(1)

    video_id = sys.argv[1]
    gdrive_folder_id = sys.argv[2]

    print(f"--- Starting manual processing for video ID: {video_id} ---")
    print(f"Google Drive Folder ID: {gdrive_folder_id}")

    # --- Environment Variable Check ---
    required_vars = {
        "YOUTUBE_API_KEY": os.environ.get("YOUTUBE_API_KEY"),
        "GDRIVE_CLIENT_SECRET_JSON": os.environ.get("GDRIVE_CLIENT_SECRET_JSON"),
        "GDRIVE_REFRESH_TOKEN": os.environ.get("GDRIVE_REFRESH_TOKEN"),
        "RAPIDAPI_KEY": os.environ.get("RAPIDAPI_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
    }
    missing_vars = [name for name, value in required_vars.items() if not value]
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}", file=sys.stderr)
        sys.exit(1)

    youtube_api_key = required_vars["YOUTUBE_API_KEY"]
    gdrive_client_secret_json = required_vars["GDRIVE_CLIENT_SECRET_JSON"]
    gdrive_refresh_token = required_vars["GDRIVE_REFRESH_TOKEN"]

    # --- Create credential files from environment variables ---
    try:
        print("Creating Google Drive credential files from environment variables...")
        client_secret_data = json.loads(gdrive_client_secret_json)
        with open('client_secret.json', 'w') as f:
            json.dump(client_secret_data, f)

        client_info = client_secret_data.get('web') or client_secret_data.get('installed')
        if not client_info:
            raise ValueError("Invalid client secret format: 'web' or 'installed' key not found.")

        token_data = {
            "token": None,
            "refresh_token": gdrive_refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "scopes": ["https://www.googleapis.com/auth/drive"],
            "expiry": "1970-01-01T00:00:00Z"
        }
        with open('gdrive_token.json', 'w') as f:
            json.dump(token_data, f)
        print("Successfully created Google Drive credential files.")
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"ERROR: Failed to parse Google Drive credentials from environment variables: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Get Video Title ---
    video_title = get_video_title(youtube_api_key, video_id)
    if not video_title:
        sys.exit(1)

    os.environ["SOURCE_VIDEO_TITLE"] = video_title

    # --- Process Video ---
    process_command = [sys.executable, "run_all.py", video_id, "--subs", "--reaction"]
    if not run_command(process_command, f"Processing video {video_id}"):
        print(f"ERROR: Failed to process video {video_id}.", file=sys.stderr)
        sys.exit(1)
    print(f"Successfully processed video {video_id}.")

    # --- Rename and Upload ---
    try:
        print("Attempting to rename and upload files...")
        upload_success = rename_and_upload_files(video_title, gdrive_folder_id)
        if upload_success:
            print("Successfully renamed and uploaded files.")
        else:
            print("ERROR: Failed to rename and upload files.", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"--- AN UNEXPECTED ERROR OCCURRED DURING UPLOAD ---", file=sys.stderr)
        print(f"An error of type {type(e).__name__} occurred: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    print(f"\n--- Successfully completed manual processing for video ID: {video_id} ---")

if __name__ == "__main__":
    main()
