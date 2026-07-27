import argparse
import os
import subprocess
import sys
import threading
import time
import requests
import shutil
from dotenv import load_dotenv

# Try importing playwright, but don't fail immediately if not present (e.g. during initial setup)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


# Progressively looser selectors: prefer a clean mp4/m4a pair, but accept any muxed
# stream rather than aborting when YouTube has thinned the format list (SABR).
FORMAT_SELECTOR = (
    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
    "bv*[height<=1080]+ba/"
    "b[height<=1080]/"
    "bv*+ba/b"
)
FORMAT_SORT = "res:1080,fps:30,codec:h264,ext:mp4"

# Hard ceiling for a single yt-dlp invocation. Without this the process can hang until
# the GitHub Actions 6-hour job limit kills the whole run.
YTDLP_TIMEOUT_SECONDS = int(os.environ.get("YTDLP_TIMEOUT_SECONDS", "2700"))


# Cookies that actually authenticate a YouTube session. A cookie file without any
# of these is useless for bypassing bot detection.
_AUTH_COOKIE_NAMES = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID", "LOGIN_INFO",
}


def has_video_stream(path):
    """
    True if the file actually contains a video track.

    When YouTube thins the format list (SABR, or a failed n-challenge), the tail of the
    format selector can match an audio-only format: yt-dlp then exits 0 having written a
    perfectly valid m4a to video.mp4. Everything downstream — ffmpeg cutting, Remotion
    rendering — either fails confusingly or produces a black clip, so catch it here.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        # Without ffprobe we cannot tell; assume the download is fine rather than
        # discarding a good file.
        print(f"Warning: could not verify video stream ({exc}).", file=sys.stderr)
        return True
    return "video" in result.stdout


def _terminate(process):
    """Terminates a subprocess, escalating to kill if it ignores the polite request."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        print("Process ignored terminate(); killing.", file=sys.stderr)
        process.kill()
    except OSError:
        pass


def _watchdog(process, timeout_seconds, flag):
    """
    Kills `process` after `timeout_seconds` unless it exits first.

    A deadline checked inside the output loop is not enough: if yt-dlp wedges without
    printing, readline() blocks forever and nothing ever re-evaluates the deadline. That
    is how a run reaches the GitHub Actions 6-hour ceiling.
    """
    def _run():
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            flag["timed_out"] = True
            print(
                f"\nWatchdog: process exceeded {timeout_seconds}s; terminating.",
                file=sys.stderr,
            )
            _terminate(process)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def usable_cookie_file(path):
    """
    Returns the path if it holds a plausible Netscape cookie jar, else None.

    The CI step used to run `echo "$YT_COOKIES_TXT" > cookies.txt` unconditionally, so a
    missing secret produced a 1-byte file that was still handed to yt-dlp. Worse, an
    *expired* YouTube session cookie makes yt-dlp fail where no cookies at all succeed
    ("The provided YouTube account cookies are no longer valid"), so an unusable jar must
    be dropped rather than passed along.
    """
    if not path or not os.path.exists(path):
        return None

    if os.path.getsize(path) <= 32:
        print(f"Ignoring cookie file (too small to be a cookie jar): {path}", file=sys.stderr)
        return None

    now = time.time()
    auth_cookies_seen = 0
    auth_cookies_live = 0
    try:
        for cookie in parse_netscape_cookies(path):
            if cookie["name"] not in _AUTH_COOKIE_NAMES:
                continue
            auth_cookies_seen += 1
            # expires == 0 means a session cookie, which never reports as expired.
            if cookie["expires"] == 0 or cookie["expires"] > now:
                auth_cookies_live += 1
    except OSError as exc:
        print(f"Ignoring cookie file (unreadable: {exc}): {path}", file=sys.stderr)
        return None

    if auth_cookies_seen == 0:
        print(f"Ignoring cookie file (no YouTube auth cookies found): {path}", file=sys.stderr)
        return None
    if auth_cookies_live == 0:
        print(f"Ignoring cookie file (all auth cookies expired): {path}", file=sys.stderr)
        return None

    print(f"Using cookies for authentication: {path} ({auth_cookies_live} live auth cookies)")
    return path


def parse_netscape_cookies(path):
    """Parses a Netscape-format cookie jar into a list of dicts."""
    cookies = []
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            # "#HttpOnly_" is a real prefix, not a comment.
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            elif line.startswith("#") or not line:
                continue

            parts = line.split("\t")
            if len(parts) < 7:
                continue
            try:
                expires = int(float(parts[4]))
            except ValueError:
                expires = 0
            cookies.append({
                "domain": parts[0],
                "include_subdomains": parts[1] == "TRUE",
                "path": parts[2],
                "secure": parts[3] == "TRUE",
                "expires": expires,
                "name": parts[5],
                "value": parts[6],
            })
    return cookies


def download_with_ytdlp(video_id, output_path):
    """
    Primary method: Uses yt-dlp with JavaScript Challenge Solver (Deno)
    to bypass YouTube's 403 errors and bot detection.

    This is the most reliable method as of late 2025.
    """
    # Convert to absolute path to avoid path resolution issues
    output_path = os.path.abspath(output_path)
    print(f"--- Attempting yt-dlp download with JS Challenge Solver for {video_id} ---")
    print(f"Output path: {output_path}")
    
    # Check if yt-dlp is available
    ytdlp_cmd = [sys.executable, "-m", "yt_dlp"]
    
    # Check if Deno is available
    deno_path = shutil.which("deno")
    if not deno_path:
        print("Warning: Deno not found. JS Challenge Solver may not work optimally.", file=sys.stderr)
        print("Install Deno with: winget install DenoLand.Deno", file=sys.stderr)
    
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"

    # Anonymous first. A YouTube session cookie that has been rotated in the browser makes
    # yt-dlp fail on videos it downloads fine without any cookies at all, and static
    # inspection of the jar cannot tell a rotated cookie from a live one. So only reach for
    # cookies once the anonymous attempt has failed, i.e. when the video plausibly needs auth.
    cookies_path = usable_cookie_file(os.path.abspath("cookies.txt"))
    attempts = [("anonymous", None)]
    if cookies_path:
        attempts.append(("with cookies", cookies_path))

    for label, cookies in attempts:
        print(f"\n--- yt-dlp attempt: {label} ---")
        cmd = _build_ytdlp_command(ytdlp_cmd, youtube_url, output_path, cookies)
        if _run_ytdlp(cmd, output_path):
            return True

    return False


def _handle_unavailable(exc):
    print(f"\n!!! Video is unavailable from this location: {exc}", file=sys.stderr)
    print("Skipping the remaining fallbacks -- they run from the same IP and will "
          "hit the same restriction.", file=sys.stderr)


def _build_ytdlp_command(ytdlp_cmd, youtube_url, output_path, cookies_path):
    cmd = ytdlp_cmd + [
        "--js-runtimes", "deno",  # Use Deno for JS challenge solving
        "--remote-components", "ejs:npm",  # Download required NPM packages for JS challenge
        # tv_simply is rarely subject to the SABR-only experiment and needs no PO token, so
        # try it first; missing_pot keeps PO-token-less formats as candidates instead of
        # dropping them and leaving nothing for the format selector to match.
        "--extractor-args",
        "youtube:player_client=tv_simply,web_safari,default;formats=missing_pot",
        # Multi-tier so that a client with a thinned-out format list still yields something
        # rather than failing with "Requested format is not available".
        "-f", FORMAT_SELECTOR,
        "-S", FORMAT_SORT,
        "--merge-output-format", "mp4",  # Output as MP4
        "--retries", "5",
        "--fragment-retries", "10",
        "--concurrent-fragments", "4",
        "--socket-timeout", "30",
        "--no-playlist",
        "-o", output_path,
    ]
    if cookies_path:
        cmd += ["--cookies", cookies_path]
    cmd.append(youtube_url)
    return cmd


# YouTube refuses these regardless of client, cookies or retry. Nothing downstream can
# help, so stop immediately rather than spending 45 minutes in the Playwright fallback.
FATAL_PATTERNS = (
    "not made this video available in your country",
    "video is not available in your country",
    "Video unavailable",
    "This video is private",
    "This video has been removed",
    "members-only content",
)


class UnavailableVideo(Exception):
    """The video cannot be fetched from this location, by any method."""


def _run_ytdlp(cmd, output_path):
    """
    Runs one yt-dlp invocation under a watchdog. Returns True if a non-empty file exists.

    Raises UnavailableVideo when YouTube reports the video as blocked here, so callers can
    skip the remaining fallbacks -- they hit the same wall from the same IP.
    """
    print(f"Executing: {' '.join(cmd)}")

    try:
        # Use Popen for real-time output streaming
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        # Stream output in real-time, but suppress [download] progress lines to reduce log spam
        print("Download started...")
        flag = {"timed_out": False}
        _watchdog(process, YTDLP_TIMEOUT_SECONDS, flag)
        fatal_reason = None
        for line in iter(process.stdout.readline, ""):
            # Filter out download progress lines (they start with [download])
            stripped = line.strip()
            if stripped.startswith("[download]"):
                continue
            print(line, end="", flush=True)
            for pattern in FATAL_PATTERNS:
                if pattern.lower() in stripped.lower():
                    fatal_reason = stripped
                    break
        process.stdout.close()
        return_code = process.wait()
        print("Download stream finished.")

        if fatal_reason:
            raise UnavailableVideo(fatal_reason)

        if flag["timed_out"]:
            if os.path.exists(output_path):
                os.remove(output_path)
            return False

        # Check if file was created (success even if return code is non-zero)
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            if file_size == 0:
                print(f"\nOutput file exists but is empty: {output_path}", file=sys.stderr)
                os.remove(output_path)
                return False
            if not has_video_stream(output_path):
                print(
                    f"\nDownloaded file has no video stream (audio-only format selected): "
                    f"{output_path}",
                    file=sys.stderr,
                )
                os.remove(output_path)
                return False
            print(f"\nSuccessfully downloaded to {output_path} ({file_size} bytes)")
            return True

        if return_code != 0:
            print(f"\nyt-dlp exited with code {return_code} and no output file", file=sys.stderr)
            return False

        print(f"\nyt-dlp completed but output file not found at {output_path}", file=sys.stderr)
        return False

    except UnavailableVideo:
        raise  # Not a download error to retry past; the caller must stop.
    except FileNotFoundError:
        print("yt-dlp not found. Install with: pip install -U yt-dlp", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error during yt-dlp download: {e}", file=sys.stderr)
        return False


def _download_stream(label, url, dest_path, timeout=300, retries=2, headers=None, cookies=None):
    # 900s x 3 retries meant a single dead stream URL burned 45 minutes before the caller
    # even learned it had failed.
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        }
    
    # Load cookies from file if not provided
    if cookies is None:
        cookie_path = usable_cookie_file(os.path.abspath("cookies.txt"))
        if cookie_path:
            try:
                cookies = {c["name"]: c["value"] for c in parse_netscape_cookies(cookie_path)}
            except OSError as e:
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


def merge_streams(video_path, audio_path, output_path):
    """Merges video and audio streams with ffmpeg, providing detailed error info on failure."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video part file not found: {video_path}")

    video_size = os.path.getsize(video_path)
    if video_size == 0:
        raise ValueError(f"Video part file is empty: {video_path}")

    # Check if audio_path exists and is valid
    has_audio = os.path.exists(audio_path) and os.path.getsize(audio_path) > 0

    # If they are the same file, we only need one input (it's likely a muxed stream)
    if video_path == audio_path:
        print("Video and audio paths are identical; attempting to treat as muxed stream.")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
    elif not has_audio:
        print("Audio part file missing or empty; attempting to use video part only.")
        cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path
        ]

    print(f"Executing ffmpeg: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')

    if result.returncode != 0:
        # Check for a specific error: missing audio stream in a merge attempt
        err_msg = result.stderr or ""
        if "matches no streams" in err_msg and "-i" in str(cmd) and len([arg for arg in cmd if arg == "-i"]) > 1:
             print("Detected missing stream (likely audio) during merge. Retrying with video only...")
             cmd_retry = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
             result_retry = subprocess.run(cmd_retry, capture_output=True, text=True, encoding='utf-8', errors='ignore')
             if result_retry.returncode == 0:
                 print("Retry with video-only succeeded.")
                 return True

        print(f"ffmpeg failed with exit code {result.returncode}", file=sys.stderr)
        if result.stdout:
            print(f"ffmpeg stdout:\n{result.stdout}", file=sys.stderr)
        if result.stderr:
            print(f"ffmpeg stderr:\n{result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)

    return True


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
        # Note: In CI, we expect browsers to be pre-installed via workflow steps for efficiency,
        # but we keep this as a last-resort safety measure.
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
        cookie_path = usable_cookie_file(os.path.abspath("cookies.txt"))
        if cookie_path:
            try:
                cookies_list = [
                    {
                        "name": c["name"],
                        "value": c["value"].strip(),
                        "domain": c["domain"],
                        "path": c["path"],
                        "expires": c["expires"],
                        "httpOnly": False,
                        "secure": c["secure"],
                        "sameSite": "Lax",
                    }
                    for c in parse_netscape_cookies(cookie_path)
                ]
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
            merge_streams(video_part_path, audio_part_path, output_path)
            print(f"Successfully created final video at {output_path}")
            
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

        print("--- Merging RapidAPI streams with ffmpeg ---")
        merge_streams(video_part_path, audio_part_path, output_path)
        print(f"Successfully created final video at {output_path}")
        
        if os.path.exists(video_part_path): os.remove(video_part_path)
        if os.path.exists(audio_part_path): os.remove(audio_part_path)
        return True

    except Exception as e:
        print(f"RapidAPI method failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Download YouTube video via yt-dlp with fallbacks.")
    parser.add_argument("video_id", help="The YouTube Video ID")
    parser.add_argument("--output", required=True, help="Output path for the video file")
    args = parser.parse_args()

    load_dotenv()

    # 1. Try yt-dlp with JS Challenge Solver (most reliable as of late 2025)
    try:
        if download_with_ytdlp(args.video_id, args.output):
            print("Download completed using yt-dlp with JS Challenge Solver.")
            sys.exit(0)
    except UnavailableVideo as exc:
        _handle_unavailable(exc)
        sys.exit(2)

    # 2. Fallback to RapidAPI
    print("\n!!! yt-dlp method failed. Switching to RapidAPI fallback !!!\n")
    if download_youtube_video_from_api(args.video_id, args.output):
        print("Download completed using RapidAPI.")
        sys.exit(0)
    
    # 3. Fallback to Playwright
    print("\n!!! RapidAPI method failed. Switching to Playwright fallback !!!\n")
    if download_with_playwright(args.video_id, args.output):
        print("Download completed using Playwright fallback.")
        sys.exit(0)
    else:
        print("All download methods failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
