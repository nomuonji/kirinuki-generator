import os
import sys
from download_video import download_with_playwright

def test_playwright_capture_relaxed():
    video_id = "jNQXAC9IVRw" # Me at the zoo
    output_path = "tmp/test_video_relaxed.mp4"
    
    if not os.path.exists("tmp"):
        os.makedirs("tmp")

    if os.path.exists(output_path):
        os.remove(output_path)

    print(f"Testing Relaxed Playwright capture for video ID: {video_id}")
    success = download_with_playwright(video_id, output_path)

    if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        print("Test PASSED: Video captured and downloaded successfully.")
        os.remove(output_path)
    else:
        print("Test FAILED: Video capture failed.")
        sys.exit(1)

if __name__ == "__main__":
    test_playwright_capture_relaxed()
