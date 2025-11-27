import os
import sys
import subprocess
import json
from playwright.sync_api import sync_playwright

def download_with_playwright_advanced(video_id, output_path):
    """
    Playwrightでストリームを再生し、aria2cを使ってダウンロード
    """
    print(f"=== Advanced Playwright + aria2c Download for {video_id} ===")
    
    video_url_captured = None
    audio_url_captured = None
    captured_headers = {}
    captured_cookies = []
    
    def handle_request(request):
        nonlocal video_url_captured, audio_url_captured, captured_headers
        url = request.url
        
        if "googlevideo.com/videoplayback" in url:
            # ヘッダーをキャプチャ
            if not captured_headers:
                captured_headers = request.headers
            
            if "mime=video" in url and not video_url_captured:
                video_url_captured = url
                print(f"Captured video URL: {url[:80]}...")
            elif "mime=audio" in url and not audio_url_captured:
                audio_url_captured = url
                print(f"Captured audio URL: {url[:80]}...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Cookieロード
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
                print("Loaded cookies from cookies.txt")
            except Exception as e:
                print(f"Warning: {e}")
        
        page = context.new_page()
        page.on("request", handle_request)
        
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"Navigating to {youtube_url}...")
        
        try:
            page.goto(youtube_url, timeout=60000)
            page.wait_for_selector("video", timeout=30000)
            
            # 再生開始
            try:
                page.click("video", timeout=5000)
            except:
                pass
            page.evaluate("document.querySelector('video').play()")
            
            import time
            print("Waiting for stream requests...")
            for i in range(30):
                if video_url_captured and audio_url_captured:
                    print("Both URLs captured!")
                    break
                if i % 5 == 0 and i > 0:
                    print(f"  {i}s...")
                time.sleep(1)
            
            if not video_url_captured:
                print("Failed to capture video URL")
                browser.close()
                return False
            
            if not audio_url_captured:
                print("Using video URL for both (muxed stream)")
                audio_url_captured = video_url_captured
            
            # ブラウザコンテキストからCookieを取得
            captured_cookies = context.cookies()
            
            browser.close()
            
            print("\n=== Downloading with aria2c ===")
            
            # Cookieをaria2c形式に変換
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in captured_cookies if 'youtube.com' in c['domain'] or 'google.com' in c['domain']])
            
            # User-Agentとその他の重要なヘッダー
            headers = [
                f"User-Agent: {captured_headers.get('user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')}",
                f"Referer: https://www.youtube.com/watch?v={video_id}",
                "Origin: https://www.youtube.com",
                f"Cookie: {cookie_str}"
            ]
            
            # まず動画をダウンロード
            tmp_dir = os.path.dirname(output_path) or "."
            video_part = os.path.join(tmp_dir, f"video_{video_id}_aria.part")
            audio_part = os.path.join(tmp_dir, f"audio_{video_id}_aria.part")
            
            # aria2cでダウンロード
            aria2c_cmd = [
                "aria2c",
                "-x", "16",  # 16接続
                "-s", "16",
                "-o", video_part,
                video_url_captured
            ]
            
            # ヘッダーを追加
            for header in headers:
                aria2c_cmd.extend(["--header", header])
            
            print(f"Downloading video with aria2c...")
            try:
                result = subprocess.run(aria2c_cmd, capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    print(f"aria2c failed: {result.stderr}")
                    return False
                print("Video downloaded!")
            except subprocess.TimeoutExpired:
                print("aria2c timed out")
                return False
            except FileNotFoundError:
                print("ERROR: aria2c not found. Please install aria2.")
                print("  Windows: choco install aria2  or  https://github.com/aria2/aria2/releases")
                return False
            
            # 音声も同様に
            if audio_url_captured != video_url_captured:
                aria2c_cmd[aria2c_cmd.index(video_part)] = audio_part
                aria2c_cmd[-1] = audio_url_captured
                
                print(f"Downloading audio with aria2c...")
                result = subprocess.run(aria2c_cmd, capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    print(f"aria2c audio failed: {result.stderr}")
                    return False
                print("Audio downloaded!")
                
                # ffmpegでマージ
                print("Merging with ffmpeg...")
                merge_cmd = [
                    "ffmpeg", "-y",
                    "-i", video_part,
                    "-i", audio_part,
                    "-c:v", "copy",
                    "-c:a", "copy",
                    output_path
                ]
                result = subprocess.run(merge_cmd, capture_output=True)
                if result.returncode != 0:
                    print(f"ffmpeg failed: {result.stderr.decode()}")
                    return False
                
                os.remove(video_part)
                os.remove(audio_part)
            else:
                # Muxed stream - rename
                os.rename(video_part, output_path)
            
            print(f"\n✓ Download successful: {output_path}")
            print(f"  Size: {os.path.getsize(output_path):,} bytes")
            return True
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            browser.close()
            return False

if __name__ == "__main__":
    success = download_with_playwright_advanced("NSsQit9zTiE", "tmp/test_aria2c.mp4")
    sys.exit(0 if success else 1)
