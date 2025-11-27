import os
import sys
import time
from playwright.sync_api import sync_playwright

def test_playwright_debug():
    video_id = "jNQXAC9IVRw"
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    
    print(f"DEBUG: Navigating to {youtube_url}")
    
    with sync_playwright() as p:
        # Launch headless=True first to simulate CI environment
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            locale="ja-JP"
        )
        page = context.new_page()

        # Log all requests to find the video stream
        def log_request(request):
            url = request.url
            if "googlevideo.com" in url:
                print(f"REQ: {url[:100]}...")
            elif "video" in request.resource_type:
                print(f"VIDEO RESOURCE: {url[:100]}...")

        page.on("request", log_request)
        
        try:
            page.goto(youtube_url, timeout=60000)
            page.wait_for_selector("video", timeout=30000)
            
            # Try to play
            try:
                page.click("video", timeout=5000)
            except:
                pass
            page.evaluate("document.querySelector('video').play()")
            
            print("Waiting for requests...")
            time.sleep(20) # Wait 20 seconds to see logs
            
            page.screenshot(path="debug_screenshot.png")
            print("Screenshot saved.")
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    test_playwright_debug()
