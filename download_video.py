import argparse
import os
import subprocess
import sys
import time
import requests
from dotenv import load_dotenv

# Try importing playwright, but don't fail immediately if not present (e.g. during initial setup)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def _download_stream(label, url, dest_path, timeout=900, retries=3, headers=None, cookies=None):
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        }
    
    # Load cookies from file if not provided
    if cookies is None and os.path.exists("cookies.txt"):
        cookies = {}
        try:
            with open("cookies.txt", "r") as f:
                for line in f:
                    if not line.startswith("#") and line.strip():
                        parts = line.strip().split("\t")
                        if len(parts) >= 7:
                            cookies[parts[5]] = parts[6]
        except Exception as e:
            print(f"Warning: Failed to load cookies.txt: {e}", file=sys.stderr)

    for attempt in range(1, retries + 1):
        try:
            print(f"Downloading {label} to {dest_path} (attempt {attempt}/{retries})...")
            with requests.get(url, stream=True, timeout=timeout, headers=headers, cookies=cookies) as r:
                if r.status_code != 200:
                    print(f"Error downloading stream. Status: {r.status_code}, Response: {r.text[:200]}", file=sys.stderr)
                r.raise_for_status()
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            print(f"Finished downloading {label}.")
            return
        except (requests.RequestException, IOError) as e:
            print(f"Error downloading {label} (attempt {attempt}): {e}", file=sys.stderr)
            if attempt < retries:
                time.sleep(5)
            else:
                raise


def find_stream_urls(data):
    """Parses the API response to find the best video and audio stream URLs from 'adaptiveFormats'."""
    video_url, audio_url = None, None
    adaptive_formats = data.get('adaptiveFormats', [])
    if not adaptive_formats:
        print("Could not find 'adaptiveFormats' in the API response.", file=sys.stderr)
        return None, None

    print("Parsing 'adaptiveFormats'...")
    preferred_video_itags = ['137', '136', '135', '134']
    
    for stream in adaptive_formats:
        itag = str(stream.get('itag'))
        mime_type = stream.get('mimeType', '')
        if itag in preferred_video_itags and 'video/mp4' in mime_type:
            video_url = stream.get('url')
            if video_url:
                print(f"Found preferred video stream (itag {itag}).")
                break
    
    if not video_url:
        for stream in adaptive_formats:
            mime_type = stream.get('mimeType', '')
            if 'video/mp4' in mime_type:
                video_url = stream.get('url')
                itag = str(stream.get('itag'))
                if video_url:
                    print(f"Found fallback video stream (itag {itag}).")
                    break

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


def download_with_playwright(video_id, output_path):
    """
    Fallback method: Uses Playwright to capture stream URLs and download them.
    This mimics a real browser to bypass 403 errors.
    """
    if not sync_playwright:
        print("Playwright is not installed. Cannot use fallback.", file=sys.stderr)
        return False

    print(f"--- Attempting Playwright Fallback for {video_id} ---")

    # Force install browsers to ensure they exist in the current environment
    try:
        print("Ensuring Playwright browsers are installed...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        print(f"Warning: Failed to run playwright install: {e}", file=sys.stderr)
    
    video_url = None
    audio_url = None
    
    # We need to capture requests to googlevideo.com
    def handle_request(request):
        nonlocal video_url, audio_url
        url = request.url
        if "googlevideo.com/videoplayback" in url:
            # Check for mime type in URL parameters
            if "mime=video" in url:
                if not video_url:
                    print(f"Captured Video URL: {url[:50]}...")
                    video_url = url
            elif "mime=audio" in url:
                if not audio_url:
                    print(f"Captured Audio URL: {url[:50]}...")
                    audio_url = url
            else:
                # If no mime type specified in URL, it might be a muxed stream or we need to check headers (harder here)
                # For now, if we don't have a video url, assume this might be it if it's large enough? 
                # Or just take the first one as video if we have nothing.
                if not video_url:
                    print(f"Captured potential Video URL (no mime): {url[:50]}...")
                    video_url = url

    with sync_playwright() as p:
        # Launch browser (headless=True for CI)
        browser = p.chromium.launch(headless=True)
        # Create a context with specific user agent and locale to look legitimate
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            locale="ja-JP"
        )
        
        # Load cookies if available
        if os.path.exists("cookies.txt"):
            cookies_list = []
            try:
                with open("cookies.txt", "r") as f:
                    for line in f:
                        if not line.startswith("#") and line.strip():
                            parts = line.strip().split("\t")
                            if len(parts) >= 7:
                                cookies_list.append({
                                    "name": parts[5],
                                    "value": parts[6].strip(),
                                    "domain": parts[0],
                                    "path": parts[2],
                                    "expires": int(parts[4]),
                                    "httpOnly": False,
                                    "secure": parts[3] == "TRUE",
                                    "sameSite": "Lax"
                                })
                context.add_cookies(cookies_list)
                print("Loaded cookies into Playwright context.")
            except Exception as e:
                print(f"Warning: Failed to load cookies for Playwright: {e}")

        page = context.new_page()
        page.on("request", handle_request)

        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"Navigating to {youtube_url}...")
        
        try:
            page.goto(youtube_url, timeout=60000)
            
            # Wait for video player
            try:
                page.wait_for_selector("video", timeout=30000)
            except Exception:
                print("Video element not found. Saving screenshot...", file=sys.stderr)
                page.screenshot(path="error_no_video.png")
                raise

            # Attempt to click play (sometimes needed if autoplay is blocked)
            try:
                page.click("video", timeout=5000)
                print("Clicked video element.")
            except Exception:
                print("Could not click video element (might be obscured or playing).")

            # Force play via JS
            page.evaluate("document.querySelector('video').play()")
            
            # Wait loop for requests
            print("Waiting for stream URLs...")
            for i in range(60): # Wait up to 60 seconds
                if video_url and audio_url:
                    print(f"Captured both streams! Video: {video_url[:50]}... Audio: {audio_url[:50]}...")
                    break
                if i % 5 == 0:
                    print(f"Waiting... ({i}s)")
                time.sleep(1)
                
            if not video_url:
                print("Could not capture video stream via Playwright.", file=sys.stderr)
                print(f"Captured Video: {bool(video_url)}, Captured Audio: {bool(audio_url)}")
                page.screenshot(path="error_capture_failed.png")
                browser.close()
                return False
            
            if not audio_url:
                print("Warning: Audio stream not captured. Assuming video stream contains audio (muxed) or using video stream as fallback.")
                audio_url = video_url

            # Now download using the captured URLs
            # Important: Use the cookies/headers from the Playwright context for the download request
            # For simplicity, we'll use requests with the cookies we loaded. 
            # Ideally we should copy headers from the captured request, but standard headers + cookies might suffice.
            
            browser.close()
            
            print("--- Downloading streams captured by Playwright ---")
            tmp_dir = os.path.dirname(output_path) or "."
            video_part_path = os.path.join(tmp_dir, f"video_{video_id}_pw.part")
            audio_part_path = os.path.join(tmp_dir, f"audio_{video_id}_pw.part")
            
            # Use the same cookies for download
            _download_stream("video (Playwright)", video_url, video_part_path)
            _download_stream("audio (Playwright)", audio_url, audio_part_path)
            
            print("--- Merging Playwright streams with ffmpeg ---")
            cmd = [
                "ffmpeg", "-y",
                "-i", video_part_path,
                "-i", audio_part_path,
                "-c:v", "copy",
                "-c:a", "copy",
                output_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(f"Successfully merged to {output_path}")
            
            # Cleanup
            if os.path.exists(video_part_path): os.remove(video_part_path)
            if os.path.exists(audio_part_path): os.remove(audio_part_path)
            
            return True

        except Exception as e:
            print(f"Playwright fallback failed: {e}", file=sys.stderr)
            browser.close()
            return False


def download_youtube_video_from_api(video_id, output_path):
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    if not rapidapi_key:
        print("Error: RAPIDAPI_KEY environment variable not set.", file=sys.stderr)
        return False

    url = "https://yt-api.p.rapidapi.com/video/info"
    querystring = {"id": video_id}
    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "yt-api.p.rapidapi.com"
    }

    print(f"--- Calling yt-api.p.rapidapi.com for video ID: {video_id} ---")
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        video_url, audio_url = find_stream_urls(data)
        if not video_url or not audio_url:
            raise ValueError("No suitable streams found in API response.")

        tmp_dir = os.path.dirname(output_path) or "."
        video_part_path = os.path.join(tmp_dir, f"video_{video_id}.part")
        audio_part_path = os.path.join(tmp_dir, f"audio_{video_id}.part")

        print("--- Starting download of separate streams (RapidAPI) ---")
        _download_stream("video", video_url, video_part_path)
        _download_stream("audio", audio_url, audio_part_path)

        print("--- Merging video and audio with ffmpeg ---")
        cmd = [
            "ffmpeg", "-y",
            "-i", video_part_path,
            "-i", audio_part_path,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Successfully merged to {output_path}")
        
        if os.path.exists(video_part_path): os.remove(video_part_path)
        if os.path.exists(audio_part_path): os.remove(audio_part_path)
        return True

    except Exception as e:
        print(f"RapidAPI method failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Download YouTube video via RapidAPI with Playwright fallback.")
    parser.add_argument("video_id", help="The YouTube Video ID")
    parser.add_argument("--output", required=True, help="Output path for the video file")
    args = parser.parse_args()

    load_dotenv()

    # 1. Try RapidAPI
    if download_youtube_video_from_api(args.video_id, args.output):
        print("Download completed using RapidAPI.")
        sys.exit(0)
    
    # 2. Fallback to Playwright
    print("\n!!! RapidAPI method failed. Switching to Playwright fallback !!!\n")
    if download_with_playwright(args.video_id, args.output):
        print("Download completed using Playwright fallback.")
        sys.exit(0)
    else:
        print("All download methods failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
