import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

video_id = sys.argv[1] if len(sys.argv) > 1 else "jNQXAC9IVRw"
output = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/playwright.mp4")
output.parent.mkdir(parents=True, exist_ok=True)

captured = {}

def classify(url):
    if "googlevideo.com/videoplayback" not in url:
        return None
    q = parse_qs(urlparse(url).query)
    mime = (q.get("mime") or [""])[0]
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return None

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--autoplay-policy=no-user-gesture-required"],
    )
    context = browser.new_context(
        locale="en-US",
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
        ),
        # YouTube embeds reject direct top-level navigation with Error 153 when
        # no HTTP Referer/client identity is present.
        extra_http_headers={"Referer": "https://example.com/"},
    )
    page = context.new_page()

    def on_request(req):
        kind = classify(req.url)
        if kind and kind not in captured:
            captured[kind] = {
                "url": req.url,
                "headers": req.headers,
            }
            print(f"captured_{kind}=1")

    page.on("request", on_request)
    embed = f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&playsinline=1"
    print("navigate=", embed)
    page.goto(embed, wait_until="domcontentloaded", timeout=60000)

    try:
        page.wait_for_selector("video", state="attached", timeout=30000)
        status = page.evaluate("""() => {
          const v = document.querySelector('video');
          v.muted = false;
          const p = v.play();
          return {paused: v.paused, readyState: v.readyState, src: v.currentSrc};
        }""")
        print("video_state=", status)
    except Exception as exc:
        print("video_element_error=", repr(exc))

    deadline = time.monotonic() + 35
    while time.monotonic() < deadline and not ("video" in captured and "audio" in captured):
        page.wait_for_timeout(1000)

    print("captured_video=", "video" in captured)
    print("captured_audio=", "audio" in captured)

    if not captured:
        title = page.title()
        body = page.locator("body").inner_text(timeout=5000)[:1000]
        print("page_title=", title)
        print("page_body=", body.replace("\n", " ")[:1000])
        browser.close()
        raise SystemExit("No googlevideo stream requests were observed")

    parts = {}
    for kind in ("video", "audio"):
        item = captured.get(kind)
        if not item:
            continue
        headers = {
            k: v
            for k, v in item["headers"].items()
            if k.lower() in {"user-agent", "referer", "origin", "accept", "accept-language"}
        }
        response = context.request.get(item["url"], headers=headers, timeout=120000)
        print(f"{kind}_status=", response.status)
        print(f"{kind}_content_type=", response.headers.get("content-type"))
        if not response.ok:
            raise SystemExit(f"Captured {kind} stream returned HTTP {response.status}")
        path = output.parent / f"playwright-{kind}.part"
        data = response.body()
        path.write_bytes(data)
        print(f"{kind}_bytes=", len(data))
        parts[kind] = path

    browser.close()

if "video" not in parts:
    raise SystemExit("No downloadable video stream was captured")

if "audio" in parts:
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(parts["video"]), "-i", str(parts["audio"]),
        "-c", "copy", str(output),
    ]
else:
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(parts["video"]), "-c", "copy", str(output),
    ]

print("ffmpeg_merge=1")
subprocess.run(cmd, check=True, timeout=120)
print("output_bytes=", output.stat().st_size)
