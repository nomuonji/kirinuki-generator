import argparse
import os
import yt_dlp

def download_youtube_video(video_url_or_id, output_path):
    """Downloads a YouTube video to the specified path."""
    # Ensure the output directory exists
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # yt-dlp options
    # -f 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best': Select best quality mp4
    # -o <path>: Specify output path template
    # --merge-output-format mp4: Merge video and audio into an mp4 container
    ydl_opts = {
        'format': 'bv*+ba/b',
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'concurrent_fragment_downloads': 1,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'outtmpl': output_path,
        'ignoreerrors': False,
    }

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
    args = parser.parse_args()

    download_youtube_video(args.video_id, args.output)

if __name__ == "__main__":
    main()
