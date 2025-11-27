import os
import sys
import subprocess
import re
from playwright.sync_api import sync_playwright

def download_with_chunk_collection(video_id, output_path):
    """
    すべてのストリームチャンクをキャプチャして結合
    """
    print(f"=== Chunk Collection Download for {video_id} ===")
    
    video_chunks = []  # (range_start, data) のリスト
    audio_chunks = []
    video_base_url = None
    audio_base_url = None
    
    def get_url_base(url):
        """URLからrange以外のベース部分を抽出"""
        # rangeパラメータを除去
        return re.sub(r'[&?]range=[\d-]+', '', url)
    
    def get_range_from_url(url):
        """URLからrange値を抽出 (例: "range=0-500000" -> (0, 500000))"""
        match = re.search(r'[&?]range=(\d+)-(\d+)', url)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None
    
    def handle_response(response):
        nonlocal video_base_url, audio_base_url
        
        url = response.url
        if "googlevideo.com/videoplayback" in url and response.status == 200:
            try:
                content_type = response.headers.get('content-type', '')
                
                # URLのベース部分を取得
                url_base = get_url_base(url)
                range_info = get_range_from_url(url)
                
                # レスポンスボディを取得
                body = response.body()
                
                if "mime=video" in url or ("mime=audio" not in url and not video_base_url):
                    # 動画チャンク
                    if not video_base_url:
                        video_base_url = url_base
                        print(f"Video stream detected: {url_base[:60]}...")
                    
                    if url_base == video_base_url:
                        start = range_info[0] if range_info else 0
                        video_chunks.append((start, body))
                        print(f"  Video chunk: {len(body):,} bytes (range: {range_info})")
                
                elif "mime=audio" in url:
                    # 音声チャンク
                    if not audio_base_url:
                        audio_base_url = url_base
                        print(f"Audio stream detected: {url_base[:60]}...")
                    
                    if url_base == audio_base_url:
                        start = range_info[0] if range_info else 0
                        audio_chunks.append((start, body))
                        print(f"  Audio chunk: {len(body):,} bytes (range: {range_info})")
                        
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
            
            # 動画情報を取得
            duration_sec = page.evaluate("document.querySelector('video').duration")
            print(f"Video duration: {duration_sec:.1f} seconds")
            
            # 再生開始
            try:
                page.click("video", timeout=5000)
                print("Clicked video")
            except:
                pass
            
            page.evaluate("document.querySelector('video').play()")
            
            # 動画全体をプリロードさせるために、何度かシーク
            import time
            print("Preloading video chunks...")
            
            # 最後までシークして全チャンクをロード
            seek_points = [0, 0.25, 0.5, 0.75, 0.9, 1.0]
            for point in seek_points:
                seek_time = duration_sec * point
                page.evaluate(f"document.querySelector('video').currentTime = {seek_time}")
                print(f"  Seeking to {seek_time:.1f}s ({int(point*100)}%)...")
                time.sleep(3)  # チャンクがロードされるまで待機
            
            # 最後に先頭に戻す
            page.evaluate("document.querySelector('video').currentTime = 0")
            time.sleep(2)
            
            print(f"\nCollected {len(video_chunks)} video chunks, {len(audio_chunks)} audio chunks")
            
            browser.close()
            
            if not video_chunks:
                print("Failed to capture video chunks")
                return False
            
            print(f"\n=== Assembling chunks ===")
            
            tmp_dir = os.path.dirname(output_path) or "."
            video_part = os.path.join(tmp_dir, f"video_{video_id}_chunks.part")
            audio_part = os.path.join(tmp_dir, f"audio_{video_id}_chunks.part")
            
            # 動画チャンクをソートして結合
            video_chunks.sort(key=lambda x: x[0])  # range開始位置でソート
            total_video_size = 0
            with open(video_part, 'wb') as f:
                for start, data in video_chunks:
                    f.write(data)
                    total_video_size += len(data)
            print(f"Video assembled: {total_video_size:,} bytes ({total_video_size/(1024*1024):.2f} MB)")
            
            # 音声チャンクも同様に
            if audio_chunks and audio_base_url != video_base_url:
                audio_chunks.sort(key=lambda x: x[0])
                total_audio_size = 0
                with open(audio_part, 'wb') as f:
                    for start, data in audio_chunks:
                        f.write(data)
                        total_audio_size += len(data)
                print(f"Audio assembled: {total_audio_size:,} bytes ({total_audio_size/(1024*1024):.2f} MB)")
                
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
                # Muxed stream
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(video_part, output_path)
                print("Saved as muxed stream")
            
            final_size = os.path.getsize(output_path)
            print(f"\n✓ Download successful: {output_path}")
            print(f"  Final size: {final_size:,} bytes ({final_size/(1024*1024):.2f} MB)")
            
            if final_size < 1000:
                print("  WARNING: File seems too small")
                return False
            
            return True
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            browser.close()
            return False

if __name__ == "__main__":
    # テスト
    success = download_with_chunk_collection("jNQXAC9IVRw", "tmp/test_chunks.mp4")
    if success:
        print("\n=== Testing with target video ===")
        success = download_with_chunk_collection("NSsQit9zTiE", "tmp/test_target_chunks.mp4")
    
    sys.exit(0 if success else 1)
