import os
import sys
import yt_dlp

def test_yt_dlp_with_extractor_args():
    video_id = "NSsQit9zTiE"
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    output_path = "tmp/test_yt_dlp_advanced.mp4"
    
    if not os.path.exists("tmp"):
        os.makedirs("tmp")

    if os.path.exists(output_path):
        os.remove(output_path)

    print(f"Testing yt-dlp with advanced options for: {video_url}")
    print("=" * 80)
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': False,
        'no_warnings': False,
        'extractor_args': {'youtube': {'player_client': ['web_embedded', 'web', 'tv_embedded']}},
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    # Add cookies if available
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'
        print("Using cookies.txt")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        print("=" * 80)
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"✓ Test PASSED: Video downloaded successfully.")
            print(f"  File: {output_path}")
            print(f"  Size: {file_size:,} bytes ({file_size / (1024*1024):.2f} MB)")
        else:
            print("✗ Test FAILED: Output file not found.")
            sys.exit(1)
            
    except Exception as e:
        print("=" * 80)
        print(f"✗ Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_yt_dlp_with_extractor_args()
