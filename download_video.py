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
import argparse
import os
import sys
import yt_dlp
from dotenv import load_dotenv

def download_video_ytdlp(video_id, output_path):
    """
    Downloads a YouTube video using yt-dlp.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Downloading video {video_id} to {output_path} using yt-dlp...")

    # Ensure the output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Configure yt-dlp options
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',  # Prefer MP4
        'outtmpl': output_path,  # Output filename
        'merge_output_format': 'mp4',  # Ensure final container is mp4
        'quiet': False,
        'no_warnings': False,
        # 'verbose': True, # Enable for debugging
    }

    # Check for cookies.txt and add to options if present
    if os.path.exists("cookies.txt"):
        print("Using cookies.txt for authentication.")
        ydl_opts['cookiefile'] = "cookies.txt"
    else:
        print("Warning: cookies.txt not found. Download might fail for age-restricted or member-only videos.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print(f"Successfully downloaded video to {output_path}")
        return True
    except yt_dlp.utils.DownloadError as e:
        print(f"Error downloading video: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Download YouTube video using yt-dlp.")
    parser.add_argument("video_id", help="The YouTube Video ID")
    parser.add_argument("--output", required=True, help="Output path for the video file")
    args = parser.parse_args()

    load_dotenv()

    success = download_video_ytdlp(args.video_id, args.output)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
