import argparse
import os
import sys
import yt_dlp

def download_youtube_video(video_url_or_id, output_path, cookie_file=None, limit_rate=None):
    """Downloads a YouTube video to the specified path."""
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': 1,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'outtmpl': output_path,
        'ignoreerrors': False,
        'user_agent': 'com.google.android.youtube/19.22.36 (Linux; U; Android 12; Pixel 5 Build/SP1A.210812.015.A4)',
        'force_ipv4': True,
    }

    if cookie_file and os.path.exists(cookie_file):
        print(f"Using cookies from: {cookie_file}")
        ydl_opts['cookiefile'] = cookie_file
    
    if limit_rate:
        print(f"Limiting download rate to: {limit_rate}")
        ydl_opts['ratelimit'] = limit_rate

    video_url = video_url_or_id
    if not video_url_or_id.startswith(('http', 'https')):
        video_url = f'https://www.youtube.com/watch?v={video_url_or_id}'

    print(f"Downloading video from: {video_url}")
    print(f"Saving to: {output_path}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print("\nDownload complete!")
    except yt_dlp.utils.DownloadError as e:
        if 'HTTP Error 403' in str(e):
            print(f"\n[SKIP] Download failed with HTTP Error 403. This video might be private or subscriber-only.", file=sys.stderr)
            print(f"URL: {video_url}", file=sys.stderr)
            sys.exit(10)
        else:
            print(f"\nAn unhandled download error occurred: {e}", file=sys.stderr)
            raise
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        raise

def main():
    parser = argparse.ArgumentParser(description="Download a YouTube video for the Kirinuki Generator.")
    parser.add_argument("video_id", help="The YouTube video ID or full URL.")
    parser.add_argument("--output", default="tmp/video.mp4", help="Output path for the downloaded video. Defaults to 'tmp/video.mp4'.")
    parser.add_argument("--cookies", help="Path to a cookies file in Netscape format.", default=None)
    parser.add_argument("--limit-rate", help="Download speed limit (e.g., 10M).", default=None)
    args = parser.parse_args()

    download_youtube_video(args.video_id, args.output, args.cookies, args.limit_rate)

if __name__ == "__main__":
    main()
