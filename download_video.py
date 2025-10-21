import argparse
import os
import sys
import yt_dlp

def download_youtube_video(video_url_or_id, output_path, cookie_file=None, limit_rate=None):
    """
    Downloads a YouTube video, retrying with advanced options if the initial attempt fails with a 403 error.
    """
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    video_url = video_url_or_id
    if not video_url_or_id.startswith(('http', 'https')):
        video_url = f'https://www.youtube.com/watch?v={video_url_or_id}'

    # --- Basic Download Options ---
    base_opts = {
        'format': 'best[ext=mp4]/best',
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'outtmpl': output_path,
        'ignoreerrors': False,
        'force_ipv4': True,
    }
    if limit_rate:
        base_opts['ratelimit'] = limit_rate

    # --- First Attempt (Simple Download) ---
    print(f"--- Attempting simple download for {video_url} ---")
    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            ydl.download([video_url])
        print("\nSimple download successful!")
        return  # Exit the function on success
    except yt_dlp.utils.DownloadError as e:
        error_str = str(e)
        if 'HTTP Error 403' in error_str or 'Sign in to confirm' in error_str:
            print(f"\nSimple download failed ({'403' if '403' in error_str else 'Sign-in required'}). Retrying with advanced options...", file=sys.stderr)
        else:
            print(f"\nAn unhandled download error occurred during simple download: {e}", file=sys.stderr)
            raise  # Re-raise for other errors
    except Exception as e:
        print(f"\nAn unexpected error occurred during simple download: {e}", file=sys.stderr)
        raise

    # --- Second Attempt (Advanced Download with Cookies & User Agent) ---
    print(f"--- Attempting advanced download for {video_url} ---")

    advanced_opts = base_opts.copy()
    advanced_opts.update({
        'concurrent_fragment_downloads': 1,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'user_agent': 'com.google.android.youtube/19.22.36 (Linux; U; Android 12; Pixel 5 Build/SP1A.210812.015.A4)',
    })

    if cookie_file and os.path.exists(cookie_file):
        print(f"Using cookies from: {cookie_file}")
        advanced_opts['cookiefile'] = cookie_file
    else:
        print("Warning: Advanced download requested but no cookie file found or provided.", file=sys.stderr)

    try:
        with yt_dlp.YoutubeDL(advanced_opts) as ydl:
            ydl.download([video_url])
        print("\nAdvanced download successful!")
    except yt_dlp.utils.DownloadError as e:
        error_str = str(e)
        if 'HTTP Error 403' in error_str or 'Sign in to confirm' in error_str:
            print(f"\n[SKIP] Advanced download also failed ({'403' if '403' in error_str else 'Sign-in required'}). This video is likely private or requires login.", file=sys.stderr)
            print(f"URL: {video_url}", file=sys.stderr)
            sys.exit(10)  # Exit with skippable code
        else:
            print(f"\nAn unhandled download error occurred during advanced download: {e}", file=sys.stderr)
            raise  # Re-raise for other errors
    except Exception as e:
        print(f"\nAn unexpected error occurred during advanced download: {e}", file=sys.stderr)
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
