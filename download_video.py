import argparse
import os
import yt_dlp

def download_youtube_video(video_url_or_id, output_path, browser_for_cookies=None):
    """Downloads a YouTube video to the specified path."""
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    ydl_opts = {
        'format': 'bv*+ba/b',
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': 1,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'outtmpl': output_path,
        'ignoreerrors': False,
    }

    if browser_for_cookies:
        print(f"Attempting to use cookies from: {browser_for_cookies}")
        ydl_opts['cookiesfrombrowser'] = (browser_for_cookies, )

    video_url = video_url_or_id
    if not video_url_or_id.startswith(('http', 'https')):
        video_url = f'https://www.youtube.com/watch?v={video_url_or_id}'

    print(f"Downloading video from: {video_url}")
    print(f"Saving to: {output_path}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print("\nDownload complete!")
    except Exception as e:
        print(f"\nAn error occurred during download: {e}")
        raise

def main():
    parser = argparse.ArgumentParser(description="Download a YouTube video for the Kirinuki Generator.")
    parser.add_argument("video_id", help="The YouTube video ID or full URL.")
    parser.add_argument("--output", default="tmp/video.mp4", help="Output path for the downloaded video. Defaults to 'tmp/video.mp4'.")
    parser.add_argument("--cookies-from-browser", help="The name of the browser to load cookies from (e.g., chrome, firefox).", default=None)
    args = parser.parse_args()

    download_youtube_video(args.video_id, args.output, args.cookies_from_browser)

if __name__ == "__main__":
    main()
