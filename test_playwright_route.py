import os
import sys
from playwright.sync_api import sync_playwright

def download_with_playwright_route(video_id, output_path):
    """
    Playwrightのpage.routeを使用して、ブラウザ内でのダウンロードを完全にキャプチャします。
    """
    print(f"=== Playwright Route-based Download for {video_id} ===")
    
    video_stream_data = []
    audio_stream_data = []
    video_url_captured = None
    audio_url_captured = None
    
    def handle_route(route, request):
        nonlocal video_url_captured, audio_url_captured
        url = request.url
        
        if "googlevideo.com/videoplayback" in url:
            # URLを記録
            if "mime=video" in url and not video_url_captured:
                video_url_captured = url
                print(f"Captured video URL: {url[:80]}...")
            elif "mime=audio" in url and not audio_url_captured:
                audio_url_captured = url
                print(f"Captured audio URL: {url[:80]}...")
        
        # すべてのリクエストを継続（ブラウザが正常にロード）
        route.continue_()
    
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
                print("Loaded cookies.")
            except Exception as e:
                print(f"Warning: {e}")
        
        page = context.new_page()
        
        # ルートをインターセプト
        page.route("**/*", handle_route)
        
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
                time.sleep(1)
            
            if not video_url_captured:
                print("Failed to capture video URL")
                browser.close()
                return False
            
            if not audio_url_captured:
                print("Using video URL as audio (muxed stream)")
                audio_url_captured = video_url_captured
            
            browser.close()
            
            # ここまではURL取得のみ。実際のダウンロードはrequestsで行う（前回と同じ問題に直面）
            # 別アプローチ: ブラウザAPIを使った直接ダウンロードが必要
            
            print("\\nURL capture successful, but download still requires different approach...")
            print(f"Video URL: {video_url_captured[:100]}")
            print(f"Audio URL: {audio_url_captured[:100]}")
            
            return False  # まだ完全な実装ではない
            
        except Exception as e:
            print(f"Error: {e}")
            browser.close()
            return False

if __name__ == "__main__":
    download_with_playwright_route("NSsQit9zTiE", "tmp/test_route.mp4")
