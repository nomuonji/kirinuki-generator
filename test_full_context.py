import os
import sys
import requests
from playwright.sync_api import sync_playwright

def download_with_full_context(video_id, output_path):
    """
    PlaywrightでURLとCookie、ヘッダーを完全に取得し、requestsでダウンロード
    """
    print(f"=== Full Context Download for {video_id} ===")
    
    video_url_captured = None
    audio_url_captured = None
    captured_request_headers = {}
    
    def handle_request(request):
        nonlocal video_url_captured, audio_url_captured, captured_request_headers
        url = request.url
        
        if "googlevideo.com/videoplayback" in url:
            # 最初のgooglevideoリクエストのヘッダーをキャプチャ
            if not captured_request_headers:
                captured_request_headers = dict(request.headers)
                print(f"Captured request headers ({len(captured_request_headers)} headers)")
            
            # より柔軟なキャプチャ
            if "mime=video" in url or ("mime=audio" not in url and not video_url_captured):
                if not video_url_captured:
                    video_url_captured = url
                    print(f"Captured video URL: {url[:80]}...")
            if "mime=audio" in url:
                if not audio_url_captured:
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
                print("Loaded cookies")
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
            browser_cookies = context.cookies()
            
            browser.close()
            
            print("\n=== Downloading with requests (full context) ===")
            
            # Cookieを requests 形式に変換
            cookies_dict = {c['name']: c['value'] for c in browser_cookies if 'youtube.com' in c['domain'] or 'google.com' in c['domain']}
            
            # キャプチャしたヘッダーをクリーンアップ
            download_headers = {
                'User-Agent': captured_request_headers.get('user-agent', 'Mozilla/5.0'),
                'Accept': captured_request_headers.get('accept', '*/*'),
                'Accept-Language': captured_request_headers.get('accept-language', 'ja,en;q=0.9'),
                'Accept-Encoding': 'identity',  # gzipを無効化（動画は圧縮済み）
                'Origin': 'https://www.youtube.com',
                'Referer': f'https://www.youtube.com/watch?v={video_id}',
                'Sec-Fetch-Dest': captured_request_headers.get('sec-fetch-dest', 'video'),
                'Sec-Fetch-Mode': captured_request_headers.get('sec-fetch-mode', 'cors'),
                'Sec-Fetch-Site': captured_request_headers.get('sec-fetch-site', 'cross-site'),
            }
            
            # sec-ch-* HeadersもコピーUAヘッダーも含む）
            for key, value in captured_request_headers.items():
                if key.lower().startswith('sec-ch-'):
                    download_headers[key] = value
            
            print(f"Using {len(cookies_dict)} cookies and {len(download_headers)} headers")
            
            # ダウンロード
            tmp_dir = os.path.dirname(output_path) or "."
            video_part = os.path.join(tmp_dir, f"video_{video_id}_ctx.part")
            audio_part = os.path.join(tmp_dir, f"audio_{video_id}_ctx.part")
            
            def download_stream(url, path, label):
                print(f"Downloading {label}...")
                try:
                    with requests.get(url, headers=download_headers, cookies=cookies_dict, stream=True, timeout=600) as r:
                        print(f"  Status: {r.status_code}")
                        print(f"  Content-Type: {r.headers.get('content-type')}")
                        print(f"  Content-Length: {r.headers.get('content-length', 'unknown')}")
                        
                        if r.status_code != 200:
                            print(f"  Response preview: {r.text[:200]}")
                            return False
                        
                        r.raise_for_status()
                        
                        with open(path, 'wb') as f:
                            downloaded = 0
                            for chunk in r.iter_content(chunk_size=1024*1024):  # 1MB chunks
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if downloaded % (10*1024*1024) == 0:  # 10MB毎に表示
                                        print(f"  Downloaded: {downloaded / (1024*1024):.1f} MB")
                        
                        file_size = os.path.getsize(path)
                        print(f"  {label} complete: {file_size:,} bytes ({file_size/(1024*1024):.2f} MB)")
                        return True
                except Exception as e:
                    print(f"  Error: {e}")
                    return False
            
            if not download_stream(video_url_captured, video_part, "video"):
                return False
            
            if audio_url_captured != video_url_captured:
                if not download_stream(audio_url_captured, audio_part, "audio"):
                    return False
                
                # ffmpegでマージ
                print("\nMerging with ffmpeg...")
                import subprocess
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
                # Muxed stream
                os.rename(video_part, output_path)
            
            print(f"\n✓ Download successful: {output_path}")
            print(f"  Final size: {os.path.getsize(output_path):,} bytes ({os.path.getsize(output_path)/(1024*1024):.2f} MB)")
            return True
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            browser.close()
            return False

if __name__ == "__main__":
    success = download_with_full_context("NSsQit9zTiE", "tmp/test_full_context.mp4")
    sys.exit(0 if success else 1)
