import os
import sys
import subprocess
from playwright.sync_api import sync_playwright

def download_with_response_intercept(video_id, output_path):
    """
    page.on("response")でレスポンスボディを直接取得
    """
    print(f"=== Response Intercept Download for {video_id} ===")
    
    video_data = None
    audio_data = None
    video_captured = False
    audio_captured = False
    
    def handle_response(response):
        nonlocal video_data, audio_data, video_captured, audio_captured
        
        url = response.url
        if "googlevideo.com/videoplayback" in url and response.status == 200:
            try:
                # mime typeで判定
                if "mime=video" in url or ("mime=audio" not in url and not video_captured):
                    if not video_captured:
                        print(f"Capturing video response: {url[:60]}...")
                        print(f"  Status: {response.status}")
                        print(f"  Content-Type: {response.headers.get('content-type')}")
                        
                        # レスポンスボディを取得（これがメモリに乗る）
                        video_data = response.body()
                        video_captured = True
                        print(f"  Captured {len(video_data):,} bytes")
                
                if "mime=audio" in url:
                    if not audio_captured:
                        print(f"Capturing audio response: {url[:60]}...")
                        print(f"  Status: {response.status}")
                        
                        audio_data = response.body()
                        audio_captured = True
                        print(f"  Captured {len(audio_data):,} bytes")
                        
            except Exception as e:
                print(f"Response capture error: {e}")
    
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
        page.on("response", handle_response)
        
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"Navigating to {youtube_url}...")
        
        try:
            page.goto(youtube_url, timeout=60000)
            page.wait_for_selector("video", timeout=30000)
            
            # 再生開始
            try:
                page.click("video", timeout=5000)
                print("Clicked video")
            except:
                pass
            
            page.evaluate("document.querySelector('video').play()")
            print("Started playback")
            
            # 動画を少し再生させてストリームをロード
            import time
            print("Waiting for streams to load...")
            for i in range(45):  # 最大45秒待機
                if video_captured and (audio_captured or i > 30):
                    # 音声は30秒待っても来なければmuxedと判断
                    break
                if i % 5 == 0 and i > 0:
                    print(f"  {i}s... (video: {video_captured}, audio: {audio_captured})")
                time.sleep(1)
            
            browser.close()
            
            if not video_data:
                print("Failed to capture video data")
                return False
            
            print(f"\n=== Saving captured data ===")
            
            tmp_dir = os.path.dirname(output_path) or "."
            video_part = os.path.join(tmp_dir, f"video_{video_id}_resp.part")
            audio_part = os.path.join(tmp_dir, f"audio_{video_id}_resp.part")
            
            # 動画を保存
            with open(video_part, 'wb') as f:
                f.write(video_data)
            print(f"Saved video: {len(video_data):,} bytes")
            
            if audio_data and audio_data != video_data:
                # 音声を保存
                with open(audio_part, 'wb') as f:
                    f.write(audio_data)
                print(f"Saved audio: {len(audio_data):,} bytes")
                
                # ffmpegでマージ
                print("\nMerging with ffmpeg...")
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
                # Muxed streamまたは音声なし
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(video_part, output_path)
                print("Saved as muxed stream")
            
            final_size = os.path.getsize(output_path)
            print(f"\n✓ Download successful: {output_path}")
            print(f"  Final size: {final_size:,} bytes ({final_size/(1024*1024):.2f} MB)")
            
            # 簡易検証: ファイルが小さすぎないか
            if final_size < 1000:
                print("  WARNING: File seems too small, might be corrupted")
                # 内容を確認
                with open(output_path, 'rb') as f:
                    preview = f.read(100)
                    print(f"  File preview: {preview[:50]}")
                return False
            
            return True
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            browser.close()
            return False

if __name__ == "__main__":
    # 短い動画でテスト
    success = download_with_response_intercept("jNQXAC9IVRw", "tmp/test_response_intercept.mp4")
    sys.exit(0 if success else 1)
