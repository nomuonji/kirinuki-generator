import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

video_id = sys.argv[1] if len(sys.argv) > 1 else "jNQXAC9IVRw"
output = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/rapidapi-cdn.mp4")
key = os.environ.get("RAPIDAPI_KEY")
if not key:
    raise SystemExit("RAPIDAPI_KEY is not configured")

host = "youtube-info-download-api.p.rapidapi.com"
video_url = f"https://www.youtube.com/watch?v={video_id}"
job_url = f"https://{host}/ajax/download.php?format=360&url={quote(video_url, safe='')}"
headers = {
    "x-rapidapi-key": key,
    "x-rapidapi-host": host,
}

job_resp = requests.get(job_url, headers=headers, timeout=60)
print("job_status=", job_resp.status_code)
print("rate_remaining=", job_resp.headers.get("X-RateLimit-Units-Remaining"))
if job_resp.status_code != 200:
    print(job_resp.text[:1000], file=sys.stderr)
    raise SystemExit(2)

job = job_resp.json()
print("job_keys=", sorted(job.keys()))
progress_url = job.get("progress_url")
if not progress_url:
    print(json.dumps(job, ensure_ascii=False)[:1500], file=sys.stderr)
    raise SystemExit("provider returned no progress_url")

deadline = time.monotonic() + 150
download_url = None
last_progress = None
while time.monotonic() < deadline:
    time.sleep(2)
    pr = requests.get(progress_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    print("progress_status=", pr.status_code)
    pr.raise_for_status()
    progress = pr.json()
    state = {
        "success": progress.get("success"),
        "text": progress.get("text"),
        "progress": progress.get("progress"),
        "has_download_url": bool(progress.get("download_url")),
    }
    if state != last_progress:
        print("progress=", json.dumps(state, ensure_ascii=False))
        last_progress = state
    download_url = progress.get("download_url")
    if download_url:
        break
    if progress.get("success") == 0 and str(progress.get("text", "")).lower().startswith("error"):
        raise SystemExit(f"provider error: {progress.get('text')}")

if not download_url:
    raise SystemExit("provider timed out before producing download_url")

parsed = urlparse(download_url)
print("download_host=", parsed.hostname)
print("googlevideo_direct=", bool(parsed.hostname and parsed.hostname.endswith("googlevideo.com")))

output.parent.mkdir(parents=True, exist_ok=True)
with requests.get(download_url, stream=True, timeout=180, headers={"User-Agent": "Mozilla/5.0"}) as dl:
    print("download_status=", dl.status_code)
    print("content_type=", dl.headers.get("content-type"))
    print("content_length=", dl.headers.get("content-length"))
    dl.raise_for_status()
    with output.open("wb") as fh:
        for chunk in dl.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fh.write(chunk)

size = output.stat().st_size
print("downloaded_bytes=", size)
if size <= 0:
    raise SystemExit("downloaded file is empty")
