import requests
import subprocess
import os
import sys

def download_with_invidious(video_id, output_path):
    """
    Invidious APIを使用してYouTube動画をダウンロード
    """
    print(f"=== Invidious API Download for {video_id} ===")
    
    # 信頼できるInvidiousインスタンス
    instances = [
        "https://inv.nadeko.net",
        "https://yewtu.be",
        "https://invidious.nerdvpn.de",
    ]
    
    video_data = None
    working_instance = None
    
    for instance in instances:
        try:
            print(f"Trying instance: {instance}")
            api_url = f"{instance}/api/v1/videos/{video_id}"
            
            response = requests.get(api_url, timeout=15)
            response.raise_for_status()
            video_data = response.json()
            
            working_instance = instance
            print(f"✓ Got video data from {instance}")
            break
            
        except Exception as e:
            print(f"  Failed: {e}")
            continue
    
    if not video_data:
        print("All Invidious instances failed")
        return False
    
    print(f"\nVideo title: {video_data.get('title')}")
    print(f"Duration: {video_data.get('lengthSeconds')}s")
    
    # adaptiveFormatsから最高品質のストリームを取得
    adaptive_formats = video_data.get('adaptiveFormats', [])
    
    if not adaptive_formats:
        print("No adaptive formats available")
        return False
    
    # 動画と音声を分けて取得
    video_streams = [f for f in adaptive_formats if f.get('type', '').startswith('video')]
    audio_streams = [f for f in adaptive_formats if f.get('type', '').startswith('audio')]
    
    if not video_streams or not audio_streams:
        print("Missing video or audio streams")
        print(f"Video streams: {len(video_streams)}, Audio streams: {len(audio_streams)}")
        return False
    
    # 最高品質を選択（解像度順）
    video_stream = sorted(video_streams, key=lambda x: x.get('resolution', '0p'), reverse=True)[0]
    audio_stream = sorted(audio_streams, key=lambda x: x.get('bitrate', 0), reverse=True)[0]
    
    print(f"\nSelected video: {video_stream.get('resolution')} {video_stream.get('qualityLabel')}")
    print(f"Selected audio: {audio_stream.get('bitrate')}kbps")
    
    video_url = video_stream.get('url')
    audio_url = audio_stream.get('url')
    
    if not video_url or not audio_url:
        print("Missing stream URLs")
        return False
    
    tmp_dir = os.path.dirname(output_path) or "."
    video_part = os.path.join(tmp_dir, f"video_{video_id}_inv.part")
    audio_part = os.path.join(tmp_dir, f"audio_{video_id}_inv.part")
    
    # ダウンロード
    print("\nDownloading video...")
    try:
        with requests.get(video_url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(video_part, 'wb') as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded % (10*1024*1024) == 0:
                            print(f"  {downloaded/(1024*1024):.1f} MB")
        print(f"✓ Video downloaded: {os.path.getsize(video_part):,} bytes")
    except Exception as e:
        print(f"✗ Video download failed: {e}")
        return False
    
    print("Downloading audio...")
    try:
        with requests.get(audio_url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(audio_part, 'wb') as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded % (10*1024*1024) == 0:
                            print(f"  {downloaded/(1024*1024):.1f} MB")
        print(f"✓ Audio downloaded: {os.path.getsize(audio_part):,} bytes")
    except Exception as e:
        print(f"✗ Audio download failed: {e}")
        return False
    
    # ffmpegでマージ
    print("\nMerging with ffmpeg...")
    try:
        merge_cmd = [
            "ffmpeg", "-y",
            "-i", video_part,
            "-i", audio_part,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path
        ]
        result = subprocess.run(merge_cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            print(f"ffmpeg failed: {result.stderr.decode()}")
            return False
        
        os.remove(video_part)
        os.remove(audio_part)
        
        final_size = os.path.getsize(output_path)
        print(f"\n✓ Download successful: {output_path}")
        print(f"  Final size: {final_size:,} bytes ({final_size/(1024*1024):.2f} MB)")
        return True
        
    except Exception as e:
        print(f"Merge failed: {e}")
        return False

if __name__ == "__main__":
    # テスト
    success = download_with_invidious("jNQXAC9IVRw", "tmp/test_invidious_short.mp4")
    if success:
        print("\n" + "="*80)
        print("Testing with target video...")
        print("="*80 + "\n")
        success = download_with_invidious("NSsQit9zTiE", "tmp/test_invidious_target.mp4")
    
    sys.exit(0 if success else 1)
