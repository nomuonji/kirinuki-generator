import argparse
import os
import time
import requests
import ffmpeg
import sys
from dotenv import load_dotenv

def find_stream_urls(data):
    """Parses the API response to find the best video and audio stream URLs from 'adaptiveFormats'."""
    video_url, audio_url = None, None

    adaptive_formats = data.get('adaptiveFormats', [])
    if not adaptive_formats:
        print("Could not find 'adaptiveFormats' in the API response.", file=sys.stderr)
        return None, None

    print("Parsing 'adaptiveFormats'...")

    # Find the best available video stream (MP4, preferring 1080p, then 720p, etc.)
    preferred_video_itags = ['137', '136', '135', '134']
    
    # First pass: look for preferred itags
    for stream in adaptive_formats:
        itag = str(stream.get('itag'))
        mime_type = stream.get('mimeType', '')
        if itag in preferred_video_itags and 'video/mp4' in mime_type:
            video_url = stream.get('url')
            if video_url:
                print(f"Found preferred video stream (itag {itag}).")
                break
    
    # Second pass: if no preferred video found, take any mp4 video
    if not video_url:
        for stream in adaptive_formats:
            mime_type = stream.get('mimeType', '')
            if 'video/mp4' in mime_type:
                video_url = stream.get('url')
                itag = str(stream.get('itag'))
                if video_url:
                    print(f"Found fallback video stream (itag {itag}).")
                    break

    # Find the best available audio stream (m4a)
    preferred_audio_itag = '140'
    for stream in adaptive_formats:
        itag = str(stream.get('itag'))
        mime_type = stream.get('mimeType', '')
        if itag == preferred_audio_itag and 'audio/mp4' in mime_type:
            audio_url = stream.get('url')
            if audio_url:
                print(f"Found preferred audio stream (itag {itag}).")
                break

    return video_url, audio_url

def _download_stream(label, url, dest_path, timeout=900, retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Referer": "https://www.youtube.com/",
        "Origin": "https://www.youtube.com",
    }
    for attempt in range(1, retries + 1):
        try:
            print(f"Downloading {label} to {dest_path} (attempt {attempt}/{retries})...")
            with requests.get(url, stream=True, timeout=timeout, headers=headers) as r:
                if r.status_code != 200:
                    print(f"Error downloading stream. Status: {r.status_code}, Response: {r.text[:200]}", file=sys.stderr)
                r.raise_for_status()
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            size = os.path.getsize(dest_path)
            if size == 0:
                raise IOError(f"{label} download resulted in an empty file.")
            print(f"{label.capitalize()} part downloaded successfully. Size: {size} bytes")
            return
        except Exception as exc:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            if attempt == retries:
                raise
            wait = min(30, 2 ** attempt)
            print(f"  -> {label.capitalize()} download failed ({exc}). Retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)


def download_youtube_video_from_api(video_id, output_path):
    load_dotenv()
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        raise ValueError("RAPIDAPI_KEY not found in environment variables.")

    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    api_url = f"https://yt-api.p.rapidapi.com/dl"
    headers = { "x-rapidapi-key": api_key, "x-rapidapi-host": "yt-api.p.rapidapi.com" }
    params = {"id": video_id}

    print(f"--- Calling yt-api.p.rapidapi.com for video ID: {video_id} ---")

    video_part_path = os.path.join(output_dir, f"video_{video_id}.part")
    audio_part_path = os.path.join(output_dir, f"audio_{video_id}.part")
    
    api_response = None
    try:
        api_response = requests.get(api_url, headers=headers, params=params, timeout=45)
        api_response.raise_for_status()
        data = api_response.json()

        video_url, audio_url = find_stream_urls(data)

        if not video_url or not audio_url:
            print("Final API Response Snippet:", str(data)[:1000], file=sys.stderr)
            raise ValueError("Could not find a valid video or audio URL in 'adaptiveFormats'.")

        print("--- Starting download of separate streams ---")
        _download_stream("video", video_url, video_part_path)
        _download_stream("audio", audio_url, audio_part_path)

        print("\n--- Merging video and audio streams with ffmpeg ---")
        input_video = ffmpeg.input(video_part_path)
        input_audio = ffmpeg.input(audio_part_path)

        out, err = (
            ffmpeg
            .output(input_video, input_audio, output_path, vcodec='copy', acodec='copy')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print(f"Successfully merged streams to {output_path}")
        print(f"Final file size: {os.path.getsize(output_path)} bytes")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        if 'err' in locals() and err:
             print("--- FFMPEG STDERR ---", file=sys.stderr)
             print(err.decode('utf-8'), file=sys.stderr)
        raise
    finally:
        if os.path.exists(video_part_path):
            os.remove(video_part_path)
        if os.path.exists(audio_part_path):
            os.remove(audio_part_path)

def main():
    parser = argparse.ArgumentParser(description="Download a YouTube video via yt-api.p.rapidapi.com.")
    parser.add_argument("video_id", help="The YouTube video ID.")
    parser.add_argument("--output", default="tmp/video.mp4", help="Output path for the video.")
    args = parser.parse_args()
    download_youtube_video_from_api(args.video_id, args.output)

if __name__ == "__main__":
    main()
