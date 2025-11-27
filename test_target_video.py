import os
import sys
from download_video import download_with_playwright

def test_target_video():
    video_id = "NSsQit9zTiE"  # Target video
    output_path = "tmp/test_target.mp4"
    
    if not os.path.exists("tmp"):
        os.makedirs("tmp")

    if os.path.exists(output_path):
        os.remove(output_path)

    print(f"Testing Playwright fallback for video ID: {video_id}")
    print("=" * 80)
    
    success = download_with_playwright(video_id, output_path)

    print("=" * 80)
    if success and os.path.exists(output_path):
        file_size = os.path.getsize(output_path)
        print(f"✓ Test PASSED: Video downloaded successfully.")
        print(f"  File: {output_path}")
        print(f"  Size: {file_size:,} bytes ({file_size / (1024*1024):.2f} MB)")
        
        # Keep file for manual verification
        print(f"\n保存されたファイルを確認してください: {output_path}")
        print("音声が含まれているか確認が必要です。")
    else:
        print("✗ Test FAILED: Video download failed.")
        sys.exit(1)

if __name__ == "__main__":
    test_target_video()
